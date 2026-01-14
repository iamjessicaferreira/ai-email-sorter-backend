import os
import re
import requests
import time
from decouple import config

try:
    import torch
    from transformers import pipeline
    TRANSFORMERS_AVAILABLE = True
    print("[HF] transformers and torch libraries available for local classification")
except ImportError as e:
    TRANSFORMERS_AVAILABLE = False
    missing = "transformers" if "transformers" in str(e) else "torch"
    print(f"[HF] {missing} library not available. Install with: pip install transformers torch")

def get_hf_headers() -> dict[str, str]:
    """Get Hugging Face API headers with token, loading it dynamically using decouple."""
    token = config('HF_API_TOKEN', default=None)
    if token:
        return {"Authorization": f"Bearer {token}"}
    return {}

HF_API_TOKEN = config('HF_API_TOKEN', default=None)
if HF_API_TOKEN:
    print(f"[HF] API Token loaded: {'*' * (len(HF_API_TOKEN) - 4)}{HF_API_TOKEN[-4:] if len(HF_API_TOKEN) > 4 else '****'}")
else:
    print("[HF] WARNING: HF_API_TOKEN not found in environment variables")
    print("[HF] Make sure HF_API_TOKEN is set in .env file")

ZERO_SHOT_CLASSIFICATION_URLS = [
    "https://api-inference.huggingface.co/models/moritzlaurer/deberta-v3-base-zeroshot-v1",
    "https://api-inference.huggingface.co/models/facebook/bart-large-mnli",
]
SUMMARIZATION_URL = "https://api-inference.huggingface.co/models/google/pegasus-xsum"
MAX_INPUT_LENGTH = 1024

def _classify_with_groq(prompt: str, labels: list[str], categories: list[dict]) -> str | None:
    """
    Classify email using Groq API.
    
    Groq provides free, fast inference for open-source LLMs and accepts
    structured prompts similar to ChatGPT.
    """
    print("[GROQ] ===== _classify_with_groq called =====")
    print(f"[GROQ] Current working directory: {os.getcwd()}")
    print(f"[GROQ] Checking for GROQ_API_KEY in environment...")
    
    # Try multiple ways to get the API key
    groq_api_key = None
    
    # Method 1: Direct environment variable
    groq_api_key = os.getenv('GROQ_API_KEY')
    if groq_api_key:
        print(f"[GROQ] ✓ Found GROQ_API_KEY in os.getenv (length: {len(groq_api_key)})")
    else:
        print("[GROQ] ✗ GROQ_API_KEY not found in os.getenv")
    
    # Method 2: decouple.config
    if not groq_api_key:
        try:
            groq_api_key = config('GROQ_API_KEY', default=None)
            if groq_api_key:
                print(f"[GROQ] ✓ Found GROQ_API_KEY via config() (length: {len(groq_api_key)})")
            else:
                print("[GROQ] ✗ GROQ_API_KEY not found via config()")
        except Exception as e:
            print(f"[GROQ] ✗ Error loading GROQ_API_KEY via config(): {e}")
    
    if not groq_api_key:
        print("[GROQ] ❌ API key not found. Set GROQ_API_KEY in .env file or environment variables.")
        print("[GROQ] Falling back to Hugging Face API...")
        return None
    
    print("[GROQ] Attempting classification with Groq API...")
    
    try:
        # Groq API endpoint
        url = "https://api.groq.com/openai/v1/chat/completions"
        
        headers = {
            "Authorization": f"Bearer {groq_api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": "llama-3.1-8b-instant",
            "messages": [
                {
                    "role": "system",
                    "content": "You are an expert email classifier. Always respond with ONLY the exact category name or 'none', nothing else."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            "temperature": 0.1,
            "max_tokens": 50,
        }
        
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            if "choices" in data and len(data["choices"]) > 0:
                category_name = data["choices"][0]["message"]["content"].strip()
                category_name = category_name.strip('"').strip("'")
                
                if category_name.lower() == "none":
                    print("[GROQ] Classification result: none (no category fits)")
                    return None
                
                for label in labels:
                    if category_name.lower() == label.lower():
                        print(f"[GROQ] ✓ Classification successful: '{label}'")
                        return label
                
                print(f"[GROQ] ⚠️ Response '{category_name}' doesn't match any category exactly")
                print(f"[GROQ] Available categories: {labels}")
                return None
            else:
                print("[GROQ] No choices in response")
                return None
        else:
            error_msg = response.text[:200]
            print(f"[GROQ] API error (status {response.status_code}): {error_msg}")
            return None
            
    except Exception as e:
        print(f"[GROQ] ❌ Exception during Groq classification: {e}")
        import traceback
        traceback.print_exc()
        return None

# Global classifier instance (singleton pattern to avoid reloading)
_local_classifier = None
_classifier_lock = None

def _get_local_classifier():
    """
    Get or create the local classifier instance (singleton pattern).
    
    Avoids reloading the model on every request, which causes bus errors.
    """
    global _local_classifier, _classifier_lock
    
    if not TRANSFORMERS_AVAILABLE:
        return None
    
    if _local_classifier is not None:
        return _local_classifier
    
    try:
        import threading
        if _classifier_lock is None:
            _classifier_lock = threading.Lock()
        
        with _classifier_lock:
            # Double-check pattern
            if _local_classifier is not None:
                return _local_classifier
            
            print("[HF] Initializing local zero-shot classifier (first time only)...")
            import torch
            import os
            
            os.environ["TOKENIZERS_PARALLELISM"] = "false"
            
            device = 0 if torch.cuda.is_available() else -1
            device_name = "GPU" if device == 0 else "CPU"
            print(f"[HF] Using {device_name} for local classification")
            
            model_name = "typeform/distilbert-base-uncased-mnli"
            print(f"[HF] Loading model: {model_name}")
            
            _local_classifier = pipeline(
                "zero-shot-classification",
                model=model_name,
                device=device,
                model_kwargs={"torch_dtype": torch.float32}
            )
            
            print("[HF] Local classifier initialized successfully")
            return _local_classifier
            
    except Exception as e:
        print(f"[HF] Failed to initialize local classifier: {e}")
        import traceback
        traceback.print_exc()
        return None

def _classify_with_local_model(email_text: str, labels: list[str], categories: list[dict]) -> str | None:
    """
    Fallback function to classify emails using transformers library locally.
    
    Used when the Hugging Face API is unavailable.
    """
    classifier = _get_local_classifier()
    if classifier is None:
        return None
    
    try:
        print(f"[HF] Classifying with local model...")
        result = classifier(email_text, labels, multi_label=False)
        
        if result and "labels" in result and len(result["labels"]) > 0:
            predicted_category = result["labels"][0]
            scores = result.get("scores", [])
            top_score = scores[0] if scores else None
            
            print(f"[HF] Local model result: '{predicted_category}' (score: {top_score:.3f})")
            
            if top_score and top_score >= 0.15:
                return predicted_category
            else:
                print(f"[HF] Local model confidence too low ({top_score:.3f}), rejecting")
                return None
        
        return None
    except Exception as e:
        print(f"[HF] Local classification error: {e}")
        import traceback
        traceback.print_exc()
        return None

def classify_email(subject: str, body: str, categories: list[dict]) -> str | None:
    """
    Classifies an email into one of the provided categories.
    
    Uses quick matching first (subject only), then falls back to AI classification
    via Groq API (preferred) or Hugging Face zero-shot classification.
    
    Args:
        subject: Email subject line
        body: Email body content
        categories: List of category dicts with 'name', 'description', and optional 'synonyms' keys
    
    Returns:
        Category name if classification succeeds, None otherwise
    """
    # Validate categories
    if not categories or len(categories) == 0:
        print("[HF] No categories provided for classification")
        return None
    
    print(f"[MATCHING] Starting quick matching (SUBJECT ONLY) for email with subject: '{subject[:50]}...'")
    print(f"[MATCHING] Number of categories to check: {len(categories)}")
    
    subject_lower = (subject or "").lower().strip()
    print(f"[MATCHING] Subject (lowercase): '{subject_lower[:100]}...'")
    
    subject_words = re.split(r'[^\w]+', subject_lower)
    
    # Check each category
    for category in categories:
        category_name = category["name"]
        category_name_lower = category_name.lower().strip()
        synonyms = category.get("synonyms", [])
        
        print(f"[MATCHING] Checking category: '{category_name}'")
        print(f"[MATCHING]   Synonyms: {synonyms}")
        
        if len(category_name_lower) < 3:
            print(f"[MATCHING]   Skipping '{category_name}' - name too short (< 3 chars)")
            continue
        
        category_in_subject = category_name_lower in subject_lower
        category_whole_word = category_name_lower in subject_words
        
        if category_in_subject:
            print(f"[MATCHING]   ✓ Found category name '{category_name_lower}' in subject")
            if category_whole_word:
                print(f"[MATCHING]   ✓ Found as whole word - high confidence")
                print(f"[MATCHING] ✓ Quick match: '{category_name}' (whole word in subject)")
                return category_name
            else:
                print(f"[MATCHING]   ✓ Found as substring - medium confidence")
                print(f"[MATCHING] ✓ Quick match: '{category_name}' (substring in subject)")
                return category_name
        
        for synonym in synonyms:
            if synonym and len(synonym.strip()) >= 3:
                synonym_lower = synonym.lower().strip()
                synonym_in_subject = synonym_lower in subject_lower
                synonym_whole_word = synonym_lower in subject_words
                
                if synonym_in_subject:
                    print(f"[MATCHING]   ✓ Found synonym '{synonym_lower}' in subject")
                    if synonym_whole_word:
                        print(f"[MATCHING]   ✓ Found as whole word - high confidence")
                        print(f"[MATCHING] ✓ Quick match: '{category_name}' via synonym '{synonym_lower}' (whole word in subject)")
                        return category_name
                    else:
                        print(f"[MATCHING]   ✓ Found as substring - medium confidence")
                        print(f"[MATCHING] ✓ Quick match: '{category_name}' via synonym '{synonym_lower}' (substring in subject)")
                        return category_name
    
    print(f"[MATCHING] ✗ No matches found in subject - will use 100% AI for classification")
    
    clean_body = re.sub(r'<[^>]+>', ' ', body) if body else ""
    clean_body = ' '.join(clean_body.split())
    if len(clean_body) > 1200:
        clean_body = clean_body[:1000] + " ... " + clean_body[-200:]
    elif len(clean_body) > 1000:
        clean_body = clean_body[:1000]
    
    category_descriptions = []
    for category in categories:
        name = category["name"]
        description = category.get("description", "")
        synonyms = category.get("synonyms", [])
        
        desc_text = f"- {name}"
        if description:
            desc_text += f": {description}"
        if synonyms:
            desc_text += f" (also known as: {', '.join(synonyms)})"
        
        category_descriptions.append(desc_text)
    
    categories_text = "\n".join(category_descriptions)
    
    full_prompt = f"""You are an intelligent email classifier. Your task is to read the email below and categorize it into the most appropriate category from the list provided.

Available categories:
{categories_text}

Email to classify:
Subject: {subject}

Content:
{clean_body}

Instructions:
1. Read the entire email content carefully
2. Consider both the subject and the body content
3. Match the email to the category that best fits based on the category name and description
4. If the email does not clearly fit any of the categories above, respond with "none"

Respond with ONLY the exact category name (e.g., "Miscellaneous", "Family", "Technology") or "none" if no category fits."""
    
    email_text = f"Subject: {subject}\n\nContent: {clean_body}"
    labels = [category["name"] for category in categories]
    
    category_info = []
    for category in categories:
        info = category["name"]
        if category.get("description"):
            info += f" ({category['description'][:50]}...)"
        if category.get("synonyms"):
            info += f" [synonyms: {', '.join(category['synonyms'][:2])}]"
        category_info.append(info)
    
    print(f"[HF] Classifying email with subject '{subject[:50]}...'")
    print(f"[HF] Categories: {labels}")
    print(f"[HF] Category details: {category_info}")
    print(f"[HF] Email text length: {len(email_text)} chars")
    
    enhanced_text = f"""Categories available:
{categories_text}

Email to classify:
{email_text}

Task: Classify this email into one of the categories above. Consider both the category name and its description when making your decision."""
    
    # Try Groq first (preferred method)
    print(f"[HF] Step 1: Attempting Groq classification...")
    groq_result = _classify_with_groq(full_prompt, labels, categories)
    if groq_result:
        print(f"[HF] ✓ Groq classification successful: '{groq_result}'")
        return groq_result
    else:
        print(f"[HF] ✗ Groq classification failed or returned None, falling back to Hugging Face...")
    
    payload = {
        "inputs": enhanced_text,
        "parameters": {
            "candidate_labels": labels,
            "multi_label": False
        }
    }

    max_retries = 3
    retry_delay = 5
    urls_to_try = ZERO_SHOT_CLASSIFICATION_URLS
    
    for attempt in range(max_retries):
        for url_index, url in enumerate(urls_to_try):
            try:
                headers = get_hf_headers()
                has_token = bool(headers.get("Authorization"))
                token_check = config('HF_API_TOKEN', default=None)
                print(f"[HF] Making request to {url} (attempt {attempt + 1}/{max_retries}, URL {url_index + 1}/{len(urls_to_try)})")
                print(f"[HF] Token check (decouple): {'Found' if token_check else 'NOT FOUND'}")
                print(f"[HF] Has token in headers: {has_token}")
                if has_token:
                    token_preview = headers["Authorization"][:20] + "..." if len(headers["Authorization"]) > 20 else headers["Authorization"]
                    print(f"[HF] Token preview: {token_preview}")
                else:
                    print(f"[HF] WARNING: No token in headers! Check .env file and restart server.")
                
                response = requests.post(
                    url, 
                    headers=headers, 
                    json=payload,
                    timeout=30
                )
                
                if response.status_code == 503:
                    try:
                        error_data = response.json()
                        if "error" in error_data and "loading" in error_data.get("error", "").lower():
                            estimated_time = error_data.get("estimated_time", retry_delay)
                            print(f"[HF] Model is loading, waiting {estimated_time}s before retry (attempt {attempt + 1}/{max_retries})")
                            if attempt < max_retries - 1:
                                time.sleep(estimated_time)
                                break
                            else:
                                print("[HF] Model loading timeout after max retries")
                                return None
                    except:
                        print(f"[HF] Got 503 but couldn't parse error response")
                        if attempt < max_retries - 1:
                            time.sleep(retry_delay)
                            break
                        else:
                            return None
                
                if response.status_code in [410, 404]:
                    status_msg = "deprecated" if response.status_code == 410 else "not found"
                    print(f"[HF] URL {url} returned {response.status_code} ({status_msg}), trying next model...")
                    if url_index < len(urls_to_try) - 1:
                        continue
                    else:
                        print(f"[HF] ⚠️ All API models returned {response.status_code} ({status_msg})")
                        if TRANSFORMERS_AVAILABLE:
                            print(f"[HF] Attempting local classification using transformers library...")
                            try:
                                return _classify_with_local_model(email_text, labels, categories)
                            except Exception as e:
                                print(f"[HF] Local classification failed: {e}")
                                print(f"[HF] ⚠️ Hugging Face API endpoints may have changed. Consider:")
                                print(f"[HF] ⚠️ 1. Checking Hugging Face API documentation for new endpoints")
                                print(f"[HF] ⚠️ 2. Using alternative APIs (OpenAI, Anthropic, etc.)")
                                return None
                        else:
                            print(f"[HF] ⚠️ Hugging Face API endpoints may have changed. Consider:")
                            print(f"[HF] ⚠️ 1. Installing transformers library: pip install transformers")
                            print(f"[HF] ⚠️ 2. Checking Hugging Face API documentation for new endpoints")
                            print(f"[HF] ⚠️ 3. Using alternative APIs (OpenAI, Anthropic, etc.)")
                            return None
                
                if response.status_code != 200:
                    try:
                        error_data = response.json()
                        error_msg = error_data.get("error", f"HTTP {response.status_code}")
                        print(f"[HF] API error (status {response.status_code}): {error_msg}")
                    except:
                        error_text = response.text[:500]
                        print(f"[HF] API error (status {response.status_code}): {error_text}")
                        if "<!DOCTYPE html>" in error_text or "<html" in error_text.lower():
                            print(f"[HF] Received HTML response - possible URL or authentication issue")
                            print(f"[HF] URL used: {url}")
                            print(f"[HF] Headers sent: {list(headers.keys())}")
                    
                    if response.status_code == 401 and url_index < len(urls_to_try) - 1:
                        print(f"[HF] Got 401, trying next URL...")
                        continue
                    
                    if attempt < max_retries - 1:
                        time.sleep(retry_delay)
                        break
                    else:
                        return None
                
                response.raise_for_status()
                
                try:
                    data = response.json()
                except ValueError as e:
                    print(f"[HF] Invalid JSON response: {e}")
                    print(f"[HF] Response text: {response.text[:500]}")
                    if attempt < max_retries - 1:
                        time.sleep(retry_delay)
                        break
                    else:
                        return None
                
                if isinstance(data, dict):
                    if "labels" in data and len(data["labels"]) > 0:
                        predicted_category = data["labels"][0]
                        scores = data.get("scores", [])
                        top_score = scores[0] if scores else None
                        
                        if scores:
                            score_details = ", ".join([f"{label}: {score:.3f}" for label, score in zip(data["labels"], scores)])
                            print(f"[HF] All classification scores: {score_details}")
                        
                        second_score = scores[1] if len(scores) > 1 else 0
                        score_difference = top_score - second_score
                        
                        print(f"[HF] Top score: {top_score:.3f} for '{predicted_category}'")
                        if second_score > 0:
                            print(f"[HF] Second score: {second_score:.3f}, difference: {score_difference:.3f}")
                        
                        if top_score >= 0.30:
                            print(f"[HF] ✓ High confidence ({top_score:.3f}) - accepting '{predicted_category}'")
                            return predicted_category
                        elif top_score >= 0.20 and score_difference >= 0.10:
                            print(f"[HF] ✓ Medium confidence ({top_score:.3f}) with clear difference ({score_difference:.3f}) - accepting '{predicted_category}'")
                            return predicted_category
                        elif score_difference >= 0.15:
                            print(f"[HF] ✓ Low absolute score ({top_score:.3f}) but very clear choice (diff: {score_difference:.3f}) - accepting '{predicted_category}'")
                            return predicted_category
                        elif top_score >= 0.15:
                            print(f"[HF] ⚠️ Low confidence ({top_score:.3f}) with small difference ({score_difference:.3f}) - accepting '{predicted_category}' anyway")
                            return predicted_category
                        else:
                            print(f"[HF] ✗ Confidence too low ({top_score:.3f} < 0.15) or unclear choice (diff: {score_difference:.3f}) - rejecting")
                            return None
                    elif "error" in data:
                        error_msg = data.get("error", "Unknown error")
                        print(f"[HF] API returned error in response: {error_msg}")
                        return None
                elif isinstance(data, list) and len(data) > 0:
                    if isinstance(data[0], dict):
                        if "labels" in data[0] and len(data[0]["labels"]) > 0:
                            predicted_category = data[0]["labels"][0]
                            print(f"[HF] Classification successful: '{predicted_category}'")
                            return predicted_category
                        elif "error" in data[0]:
                            error_msg = data[0].get("error", "Unknown error")
                            print(f"[HF] API returned error in list response: {error_msg}")
                            return None
                
                print(f"[HF] Unexpected response format: {type(data)} - {str(data)[:200]}")
                return None
                
            except requests.exceptions.RequestException as e:
                print(f"[HF] Request error with URL {url} (attempt {attempt + 1}/{max_retries}): {e}")
                if url_index >= len(urls_to_try) - 1:
                    if attempt < max_retries - 1:
                        time.sleep(retry_delay)
                        break
                    else:
                        print("[HF] Max retries reached, giving up")
                        return None
                else:
                    continue
            except KeyError as e:
                print(f"[HF] Missing key in response: {e}")
                print(f"[HF] Response data: {data if 'data' in locals() else 'N/A'}")
                if url_index < len(urls_to_try) - 1:
                    continue
                else:
                    return None
            except Exception as error:
                print(f"[HF] Unexpected error during classification with URL {url}: {error}")
                print(f"[HF] Error type: {type(error).__name__}")
                import traceback
                print(f"[HF] Traceback: {traceback.format_exc()}")
                if url_index < len(urls_to_try) - 1:
                    continue
                else:
                    if attempt < max_retries - 1:
                        time.sleep(retry_delay)
                        break
                    else:
                        return None
    
    return None

def summarize_email(subject: str, body: str) -> str:
    email_text = f"Subject: {subject}\nBody: {body}"
    if len(email_text) > MAX_INPUT_LENGTH:
        email_text = email_text[:MAX_INPUT_LENGTH]

    try:
        headers = get_hf_headers()
        response = requests.post(SUMMARIZATION_URL, headers=headers, json={"inputs": email_text})
        response.raise_for_status()
        data = response.json()
        if isinstance(data, list) and data and 'summary_text' in data[0]:
            return data[0]['summary_text']
        return ""
    except Exception as error:
        print(f"[HF] Email summarization error: {error}")
        return ""
