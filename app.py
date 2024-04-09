# Import necessary libraries
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
import io
import json
from docx import Document
from pdfminer.high_level import extract_text
from pywebio.input import *
from pywebio.output import *
from pywebio import start_server
import os
import time
import openai
from openai import OpenAI
from dotenv import load_dotenv
from pywebio.session import run_js

# Load environment variables from the .env file
load_dotenv()
email_address = os.getenv("EMAIL_ADDRESS")
email_pass = os.getenv("EMAIL_PASS")


# Function to send the dialog via email
def send_email(subject, body, recipient):
    sender_email = email_address
    sender_password = email_pass
    # Create a multipart message
    message = MIMEMultipart()
    message["From"] = sender_email
    message["To"] = recipient
    message["Subject"] = subject

    # Add the email body to the message
    message.attach(MIMEText(body, "plain"))

    try:
        # Set up the SMTP server and send the email
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, recipient, message.as_string())
        return True
    except smtplib.SMTPAuthenticationError:
        print("Error: Authentication failed. Check your email address and password or app password.")
        return False
    except smtplib.SMTPException as e:
        print(f"Error: An SMTP error occurred - {e}")
        return False
    except Exception as e:
        print(f"Error: An unexpected error occurred - {e}")
        return False


# Open information about open vacancies.
# This better be a google doc for more dynamic content, but for development, let's keep it simple
with open("vacancies.json", "r") as file:
    vacancies_data = json.load(file)

#  Set the API key and assistant ID from environment variables
openai.api_key = os.getenv("OPENAI_API_KEY")
assistant_id = os.getenv("ASSISTANT_ID")

# Initialize the OpenAI client with the API key
client = OpenAI(
    api_key=openai.api_key
)
# Initialize the thread ID for conversation tracking
thread_id = None


# Convert the file uploaded to text for communication with Assistant
def convert_to_text(file_content, file_type):
    # Check file types and return extracted text
    if file_type == 'pdf':
        return extract_text(io.BytesIO(file_content))
    elif file_type == 'docx':
        doc = Document(io.BytesIO(file_content))
        return '\n'.join([paragraph.text for paragraph in doc.paragraphs])
    elif file_type == 'txt':
        return file_content.decode('utf-8')
    else:
        # Raise an error for unsupported file types
        raise ValueError(f"Unsupported file type: {file_type}")


# Collect user information through a form
def collect_user_info():
    # Create pywebio input fields for name, email, vacancy, and CV upload
    user_info = input_group("Your Information", [
        input("Name", name="name"),
        select("Vacancy Applying For", [vacancy["name"] for vacancy in vacancies_data], name="vacancy"),
        file_upload("Upload your CV", name="cv", accept=[".pdf", ".docx", ".doc", ".txt"])
    ])
    return user_info


# Communicate with the GPT model
def chat_with_gpt(query):
    # Use the globally set thread ID
    global thread_id
    # Retrieve assistant from ID
    my_assistant = client.beta.assistants.retrieve(assistant_id)

    if thread_id is None:
        # Create a new thread if one does not exist
        thread = client.beta.threads.create()
        thread_id = thread.id
    else:
        # Use the existing thread if it exists
        thread = client.beta.threads.retrieve(thread_id)
    # Create message
    thread_message = client.beta.threads.messages.create(
        thread_id=thread.id,
        role="user",
        content=query,
    )
    # Run thread
    run = client.beta.threads.runs.create(
        thread_id=thread.id,
        assistant_id=assistant_id,
    )
    while run.status != "completed":
        run = client.beta.threads.runs.retrieve(
            thread_id=thread.id,
            run_id=run.id
        )
    # Retrieve the latest message from the thread and return the response
    else:
        message_response = client.beta.threads.messages.list(
            thread_id=thread.id
        )
        messages = message_response.data
        latest_massage = messages[0]
        response = latest_massage.content[0].text.value

        return response


# This is how we handle the response we get and put in a pywebio table.
# Table is optional, for better readability
# Function to display the response in a PyWebIO table
def display_response(response):
    with use_scope('response_area'):
        put_table([
            [put_text("Assistant: ").style("color: #202060; font-size:16px"), response]
        ])


def main():
    # Use the global thread ID
    global thread_id
    # Reset the thread ID for a new conversation
    thread_id = None
    # Initialize an empty list to store the dialog
    dialog = []
    # Gather user information
    user_info = collect_user_info()
    # Save date and time the dialog created
    started_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    dialog.append(f"Dialog with applicant started at:\n"
                  f"{started_at}\n\n")
    # Save the user info to Dialog
    dialog.append(f"User Information: \n"
                  f"{user_info}\n\n")
    # Determine file type to pass to text converter
    file_type = user_info['cv']['filename'].split('.')[-1].lower()
    cv_content = convert_to_text(user_info['cv']['content'], file_type)
    # Retrieve selected vacancy to gather information and requirements
    selected_vacancy = next((vacancy for vacancy in vacancies_data if vacancy["name"] == user_info['vacancy']), None)
    if not selected_vacancy:
        put_text("Selected vacancy not found in the data.")
        return

    # Create readable text from vacancies file
    vacancy_details = "\n".join([
        f"Name: {selected_vacancy['name']}",
        f"Suitability Needed For the Vacancy: {selected_vacancy['suitability_needed']}",
        "Description:",
        "\n".join([f"- {req}" for req in selected_vacancy["description"][0]["requirements"]]),
        "Would be plus:",
        "\n".join([f"- {detail}" for detail in selected_vacancy["would_be_plus"][0]["details"]]),
        f"Notes: {selected_vacancy['notes']}"
    ])
    # Save to dialog vacancy details also
    dialog.append(f"Vacancy details at the time of the conversation:\n"
                  f"{vacancy_details}\n\n")
    # Create the first query and send user information with the cv content and vacancy details
    # then display the response
    query = f"Read the CV for the position of {user_info['vacancy']}:\n{cv_content}\n\n{vacancy_details}"
    # Create a dedicated output area for responses
    with put_loading():
        put_text("Analyzing your information, please wait...")
        response = chat_with_gpt(query)
    put_scope('response_area')

    dialog.append(f"Assistant: {response}")
    display_response(response)

    # Continue the conversation until a final response is received
    final_response_received = False
    while not final_response_received:
        user_answer = textarea("Your answer: ")
        dialog.append(f"--------------\nApplicant answer:\n {user_answer}\n---------------\n")
        with put_loading():
            put_text("Analyzing your answer, please wait...")
            response = chat_with_gpt(user_answer)
        if "Based on my analysis" in response:
            final_response_received = True
            display_response(response)
            dialog.append(f"Assistant: {response}")
            time.sleep(5)
            put_text("Thank you for providing your responses. Your answers have been noted.\n "
                     f"If there is anything else you would like to add or ask, feel free to let me know. \n"
                     f"Good luck with your job search and the application process!")
            # Create a popup (optional)
            popup("Thank You", f"{response}\n\nThank you for providing your responses. Your answers have been noted.\n "
                               f"If there is anything else you would like to add or ask, feel free to let me know. \n"
                               f"Good luck with your job search and the application process!")
            # Close the window after 10 seconds
            run_js('setTimeout(() => window.close(), 20000)')
        else:
            # Display the new response
            display_response(response)
            dialog.append(f"Assistant: {response}")
    # Print the full dialog for record-keeping or do something else
    full_dialog = "\n".join(dialog)
    folder_path = f"dialogs/{thread_id}"
    if not os.path.exists(folder_path):
        os.makedirs(folder_path)
    with open(f'dialogs/{thread_id}/dialog.txt', 'w') as dialog_file:
        dialog_file.write(full_dialog)

    # Save it for email sending setup
    """subject = "New ChatGPT Job Application Dialog"
    # Replace with the admins' email address
    recipient = "ozgurmtunca@gmail.com"

    # Send the email with the dialog as the body
    send_email(subject, full_dialog, recipient)

    # Display a confirmation message
    put_text("Email sent successfully!")"""


if __name__ == "__main__":
    # Run pywebio server
    start_server(main, port=3000, debug=True)
