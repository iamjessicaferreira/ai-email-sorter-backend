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
    """
    Prevents duplicate social auth associations, but allows multiple accounts
    for the same user (different uids).
    """
    if backend.name != "google-oauth2":
        return

    # Check if this uid is already associated with a different user
    social = UserSocialAuth.objects.filter(provider=backend.name, uid=uid).first()
    if social:
        if user and social.user != user:
            # This uid is already associated with a different user - prevent this
            print(f"[PIPELINE] Preventing duplicate: uid {uid} already associated with user {social.user.username}, trying to associate with {user.username}")
            raise AuthAlreadyAssociated(backend)
        # Same user, same uid - this is fine (updating existing association)
        print(f"[PIPELINE] Allowing update: uid {uid} for user {user.username if user else social.user.username}")
        return {
            "social": social,
            "user": user or social.user
        }
    
    # New uid for this user - allow it (multiple accounts)
    if user:
        print(f"[PIPELINE] Allowing new account: uid {uid} for user {user.username}")
    return None