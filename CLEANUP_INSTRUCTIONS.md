# Instruções para Limpar o Banco de Dados

## ⚠️ ATENÇÃO
Este script vai deletar **TODOS** os emails e contas Gmail do banco de dados. 
As categorias de email e usuários Django serão preservados.

## Como executar:

```bash
cd ai-email-sorter-backend
python clear_accounts.py
```

O script vai:
1. Mostrar quantos emails e contas existem
2. Pedir confirmação (digite 'SIM' para confirmar)
3. Deletar todos os emails
4. Deletar todas as contas Gmail (GmailAccount)
5. Deletar todas as autenticações sociais do Google (UserSocialAuth)

## Após a limpeza:

1. Faça logout de todas as contas no Google (se necessário)
2. Conecte as contas novamente através da interface
3. Apenas e-mails NOVOS serão processados (não retroativos)
