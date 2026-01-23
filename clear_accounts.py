#!/usr/bin/env python
"""
Script para limpar todas as contas Gmail, UserSocialAuth e emails do banco de dados.
Use com cuidado - isso apaga TODOS os dados de contas e emails!
"""
import os
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
django.setup()

from django.contrib.auth.models import User
from social_django.models import UserSocialAuth
from api.models import GmailAccount, Email, EmailCategory

def clear_all_accounts():
    """Remove todas as contas Gmail, UserSocialAuth e emails associados"""
    print("=" * 60)
    print("LIMPEZA DE BANCO DE DADOS - CONTAS E EMAILS")
    print("=" * 60)
    
    # Contar antes de deletar
    total_emails = Email.objects.count()
    total_gmail_accounts = GmailAccount.objects.count()
    total_social_auths = UserSocialAuth.objects.filter(provider='google-oauth2').count()
    
    print(f"\n[ANTES] Total de emails: {total_emails}")
    print(f"[ANTES] Total de GmailAccounts: {total_gmail_accounts}")
    print(f"[ANTES] Total de UserSocialAuth (google-oauth2): {total_social_auths}")
    
    # Confirmar
    response = input("\n⚠️  ATENÇÃO: Isso vai deletar TODOS os emails e contas Gmail. Continuar? (digite 'SIM' para confirmar): ")
    if response != 'SIM':
        print("Operação cancelada.")
        return
    
    # Deletar emails primeiro (devido a foreign keys)
    print("\n[DELETANDO] Removendo todos os emails...")
    deleted_emails = Email.objects.all().delete()
    print(f"[DELETADO] {deleted_emails[0]} emails removidos")
    
    # Deletar GmailAccounts
    print("\n[DELETANDO] Removendo todas as contas Gmail...")
    deleted_accounts = GmailAccount.objects.all().delete()
    print(f"[DELETADO] {deleted_accounts[0]} GmailAccounts removidos")
    
    # Deletar UserSocialAuth do Google
    print("\n[DELETANDO] Removendo todas as autenticações sociais do Google...")
    deleted_social = UserSocialAuth.objects.filter(provider='google-oauth2').delete()
    print(f"[DELETADO] {deleted_social[0]} UserSocialAuth removidos")
    
    # Verificar depois
    remaining_emails = Email.objects.count()
    remaining_accounts = GmailAccount.objects.count()
    remaining_social = UserSocialAuth.objects.filter(provider='google-oauth2').count()
    
    print("\n" + "=" * 60)
    print("RESULTADO FINAL")
    print("=" * 60)
    print(f"[DEPOIS] Emails restantes: {remaining_emails}")
    print(f"[DEPOIS] GmailAccounts restantes: {remaining_accounts}")
    print(f"[DEPOIS] UserSocialAuth restantes: {remaining_social}")
    print("\n✅ Limpeza concluída!")
    print("\nNOTA: Categorias de email foram preservadas.")
    print("      Usuários Django foram preservados.")

if __name__ == '__main__':
    clear_all_accounts()
