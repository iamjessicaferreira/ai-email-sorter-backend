import os
import requests

HF_API_TOKEN = os.getenv("HF_API_TOKEN")

HEADERS = {
    "Authorization": f"Bearer {HF_API_TOKEN}"
}

ZERO_SHOT_CLASSIFICATION_URL = "https://api-inference.huggingface.co/models/facebook/bart-large-mnli"
SUMMARIZATION_URL = "https://api-inference.huggingface.co/models/facebook/bart-large-cnn"
MAX_INPUT_LENGTH = 1024

def build_classification_prompt(categories, subject, body):
    category_descriptions = ", ".join([f'"{c["name"]}" ({c["description"]})' for c in categories])
    return (
        f'You are an intelligent email classifier. Your goal is to define the ideal category for the received email according to its subject and content.\n'
        f'The available categories are: {category_descriptions}\n'
        f'If none of them fit the content, set the category as "none".\n'
        f'Assign the best category for the email below based on its content.\n\n'
        f'Subject: {subject}\n\n'
        f'Body: {body}\n\n'
        f'Respond only with the exact category name or "none" if none apply.'
    )

def classify_email(subject, body, categories):
    email_text = f"Subject: {subject}\nBody: {body}"
    labels = [category["name"] for category in categories]

    payload = {
        "inputs": email_text,
        "parameters": {
            "candidate_labels": labels,
            "multi_label": False
        }
    }

    try:
        response = requests.post(ZERO_SHOT_CLASSIFICATION_URL, headers=HEADERS, json=payload)
        response.raise_for_status()
        data = response.json()
        predicted_category = data['labels'][0]
        return predicted_category
    except Exception as error:
        print(f"[HF] Email classification error: {error}")
        return None

def summarize_email(subject, body):
    email_text = f"Subject: {subject}\nBody: {body}"
    if len(email_text) > MAX_INPUT_LENGTH:
        email_text = email_text[:MAX_INPUT_LENGTH]

    try:
        response = requests.post(SUMMARIZATION_URL, headers=HEADERS, json={"inputs": email_text})
        response.raise_for_status()
        data = response.json()
        if isinstance(data, list) and data and 'summary_text' in data[0]:
            return data[0]['summary_text']
        return ""
    except Exception as error:
        print(f"[HF] Email summarization error: {error}")
        return ""
