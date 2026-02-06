# AI Email Sorter - Backend

A Django REST API that powers the AI Email Sorter. Handles Google OAuth authentication, Gmail integration via Pub/Sub, AI-powered email categorization, and real-time WebSocket notifications.

## Tech Stack

- **Django 5** + **Django REST Framework**
- **Channels** (WebSocket via Daphne/ASGI)
- **Celery** + **Redis** (async task processing)
- **Google Cloud Pub/Sub** (Gmail push notifications)
- **Social Auth** (Google OAuth2)
- **PostgreSQL** (production) / **SQLite** (development)

## Prerequisites

- Python 3.11+
- Redis (for Celery and WebSocket channel layer)
- A Google Cloud project with:
  - OAuth 2.0 credentials (Client ID + Secret)
  - Gmail API enabled
  - Pub/Sub topic and subscription configured
- The [frontend](https://github.com/iamjessicaferreira/ai-email-sorter-frontend) running locally

## Local Setup

1. **Clone the repository**

```bash
git clone https://github.com/iamjessicaferreira/ai-email-sorter-backend.git
cd ai-email-sorter-backend
```

2. **Create and activate a virtual environment**

```bash
python -m venv venv
source venv/bin/activate  # macOS/Linux
# or
venv\Scripts\activate     # Windows
```

3. **Install dependencies**

```bash
pip install -r requirements.txt
```

4. **Configure environment variables**

```bash
cp .env.example .env
```

Edit `.env` with your credentials:

```env
# Django
DJANGO_SECRET_KEY=your-secret-key
DJANGO_DEBUG=True
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1

# CORS / CSRF (must match frontend URL)
CORS_ALLOWED_ORIGINS=http://localhost:3000
CSRF_TRUSTED_ORIGINS=http://localhost:3000

# Database (SQLite for development)
DATABASE_URL=sqlite:///db.sqlite3

# Google OAuth2
SOCIAL_AUTH_GOOGLE_OAUTH2_KEY=your-google-client-id
SOCIAL_AUTH_GOOGLE_OAUTH2_SECRET=your-google-client-secret
SOCIAL_AUTH_LOGIN_REDIRECT_URL=http://localhost:3000/
SOCIAL_AUTH_LOGIN_ERROR_URL=http://localhost:3000/

# Google Cloud (Gmail API + Pub/Sub)
GOOGLE_APPLICATION_CREDENTIALS=/path/to/your/service-account.json
GCLOUD_PROJECT=your-gcloud-project-id
PUBSUB_SUBSCRIPTION_ID=your-subscription-id
GMAIL_PUBSUB_TOPIC=projects/your-project/topics/your-topic

# Redis (required for WebSocket + Celery)
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=redis://localhost:6379/0
REDIS_HOST=127.0.0.1
REDIS_PORT=6379
```

5. **Start Redis**

```bash
redis-server
```

6. **Run migrations**

```bash
python manage.py migrate
```

7. **Start the development server (Daphne for WebSocket support)**

```bash
daphne backend.asgi:application --bind 0.0.0.0 --port 8000
```

8. **Start the Celery worker (in a separate terminal)**

```bash
celery -A backend worker --loglevel=info
```

9. **Start Celery Beat for scheduled tasks (in a separate terminal)**

```bash
celery -A backend beat --loglevel=info --scheduler django_celery_beat.schedulers:DatabaseScheduler
```

The API will be available at [http://localhost:8000](http://localhost:8000).

## API Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/api/auth/login/google-oauth2/` | GET | Initiate Google OAuth flow |
| `/api/auth/success/` | GET | List connected Gmail accounts |
| `/api/auth/refresh-token/` | GET | Check if refresh token exists |
| `/api/auth/disconnect-google/` | POST | Disconnect a Gmail account |
| `/api/auth/disconnect-all-google/` | POST | Disconnect all accounts |
| `/api/categories/` | GET/POST | List or create categories |
| `/api/categories/:id/` | PUT/DELETE | Update or delete a category |
| `/api/emails/:id/` | GET | Get email details |
| `/api/emails/:id/recategorize/` | POST | Recategorize an email |
| `/api/delete-emails/` | POST | Bulk delete emails |
| `/api/unsubscribe-emails/` | POST | Bulk unsubscribe |
| `ws/emails/` | WebSocket | Real-time email notifications |

## Architecture

```
Gmail Inbox
    |
    v
Google Cloud Pub/Sub  -->  Celery Worker  -->  AI Categorization
                                |
                                v
                          Django Channels (Redis)
                                |
                                v
                          WebSocket  -->  Frontend (real-time updates)
```

## Production Notes

In production, this backend runs on [Render](https://render.com) with:
- Daphne as the ASGI server
- PostgreSQL (via Neon Database)
- `SameSite=None; Secure` cookies for cross-origin auth with the Vercel-hosted frontend

Real-time WebSocket notifications require a Redis instance. This is not provisioned in the production demo due to infrastructure costs.

## Related

- [Frontend repository](https://github.com/iamjessicaferreira/ai-email-sorter-frontend)
