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


def create_gmail_account_after_auth(backend, user, response, *args, **kwargs):
    """
    Called after successful OAuth authentication to create/update GmailAccount.
    This ensures GmailAccount is created immediately after OAuth completes.
    """
    if backend.name != 'google-oauth2' or not user:
        return
    
    try:
        from .gmail_services import update_gmail_account_from_social
        print(f"[PIPELINE] Creating/updating GmailAccount for user {user.username} after OAuth")
        update_gmail_account_from_social(user)
    except Exception as e:
        print(f"[PIPELINE] Error creating GmailAccount: {e}")
        import traceback
        traceback.print_exc()


def prevent_duplicate_social_auth(backend, uid, user=None, *args, **kwargs):
    """
    Prevents duplicate social auth associations, but allows multiple accounts
    for the same user (different uids). 
    
    IMPORTANT: We do NOT automatically transfer accounts between users.
    If a uid is already associated with a different user, we raise an error
    to prevent accidental account transfers.
    """
    if backend.name != "google-oauth2":
        return

    # Check if this uid is already associated with a different user
    social = UserSocialAuth.objects.filter(provider=backend.name, uid=uid).first()
    if social:
        if user and social.user != user:
            # This uid is already associated with a different user
            # DO NOT transfer automatically - this prevents unwanted reconnections
            print(f"[PIPELINE] BLOCKING: uid {uid} already associated with user {social.user.username}, cannot associate with {user.username}")
            print(f"[PIPELINE] User {user.username} must disconnect the account from user {social.user.username} first")
            raise AuthAlreadyAssociated(backend)
        elif not user:
            # User is None (first login) and account is already associated
            # Allow login with the existing user
            print(f"[PIPELINE] Account {uid} already associated with user {social.user.username}, allowing login")
            return {
                "social": social,
                "user": social.user
            }
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