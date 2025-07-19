

def save_email_to_extra_data(backend, details, response, uid, user=None, *args, **kwargs):
    if backend.name == 'google-oauth2':
        print("details:", details)
        print("response:", response)
        social = backend.strategy.storage.user.get_social_auth(backend.name, uid)
        print("social:", social)
        if social:
            print("Detalhes recebidos no pipeline - details:", details)
            print("Resposta completa do Google - response:", response)

            email = details.get('email') or response.get('email')
            print("email:", email)
            print("social:" , social)
            if email:
                print("Salvando email no extra_data:", email)
                social.extra_data['email'] = email
                social.save()
            else:
                print("Email não encontrado para salvar")
