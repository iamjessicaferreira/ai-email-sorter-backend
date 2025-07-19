

def save_email_to_extra_data(backend, details, response, uid, user=None, *args, **kwargs):
    if backend.name == 'google-oauth2':
        social = backend.strategy.storage.user.get_social_auth(backend.name, uid)
        if social:

            email = details.get('email') or response.get('email')
            if email:
                social.extra_data['email'] = email
                social.save()
            else:
                print("Email não encontrado para salvar")
