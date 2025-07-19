import requests
import os

HF_API_TOKEN = os.getenv("HF_API_TOKEN") 

headers = {
    "Authorization": f"Bearer {HF_API_TOKEN}"
}

def build_prompt(categories, subject, body):
    category_names = ", ".join([f'"{c["name"]}" ({c["description"]})' for c in categories])
    
    return f"""
Você é um classificador de e-mails inteligente. Seu objetivo é definir qual a categoria ideal para o e-mail recebido de acordo com seu conteúdo e título.

As categorias disponíveis para serem classificadas são: {category_names}

Se nenhuma delas fizer sentido com o conteúdo do email, defina a categoria como "none".

Atribua a melhor categoria para o e-mail abaixo com base no conteúdo.

Assunto: {subject}

Corpo: {body}

Responda somente com o nome da categoria exata ou "none" caso nenhuma delas se aplique.
""".strip()

def classify_email(subject, body, categories):
    print('entrou classify')
    text = f"Assunto: {subject}\nCorpo: {body}"
    
    # Monta prompt simples com categorias
    labels = [c["name"] for c in categories]
    # Usamos um modelo de classificação multi-label zero-shot
    API_URL = "https://api-inference.huggingface.co/models/facebook/bart-large-mnli"
    
    payload = {
        "inputs": text,
        "parameters": {
            "candidate_labels": labels,
            "multi_label": False
        }
    }
    
    try:
        response = requests.post(API_URL, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()
        # data['labels'] é lista de categorias ordenadas por score (maior primeiro)
        predicted_category = data['labels'][0]
        print(f"Categoria retornada pela HF: '{predicted_category}'")
        return predicted_category
    except Exception as e:
        print(f"[HF] Erro na classificação do e-mail: {e}")
        return None


def summarize_email(subject, body):
    print('entrou summarize')
    # Limitar tamanho do texto para evitar erro 400 (ex: 1024 caracteres)
    max_len = 1024
    text = f"Assunto: {subject}\nCorpo: {body}"
    if len(text) > max_len:
        text = text[:max_len]

    API_URL = "https://api-inference.huggingface.co/models/facebook/bart-large-cnn"
    
    try:
        response = requests.post(API_URL, headers=headers, json={"inputs": text})
        response.raise_for_status()
        data = response.json()
        if isinstance(data, list) and len(data) > 0 and 'summary_text' in data[0]:
            summary = data[0]['summary_text']
        else:
            summary = ""
        print(f"Resumo gerado pela HF: {summary}")
        return summary
    except Exception as e:
        print(f"[HF] Erro ao resumir o e-mail: {e}")
        return ""