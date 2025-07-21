from social_core.exceptions import AuthAlreadyAssociated
from social_django.models import UserSocialAuth

def save_email_to_extra_data(backend, details, response, uid, user=None, *args, **kwargs):
    if backend.name == 'google-oauth2':
        social = backend.strategy.storage.user.get_social_auth(backend.name, uid)
        if social:
            email = details.get('email') or response.get('email')
            if email:
                social.extra_data['email'] = email
                social.save()
            else:
                print("Email not found to save")


def prevent_duplicate_social_auth(backend, uid, user=None, *args, **kwargs):
    if backend.name != "google-oauth2":
        return

    social = UserSocialAuth.objects.filter(provider=backend.name, uid=uid).first()
    if social:
        if user and social.user != user:
            raise AuthAlreadyAssociated(backend)
        return {
            "social": social,
            "user": user or social.user
        }