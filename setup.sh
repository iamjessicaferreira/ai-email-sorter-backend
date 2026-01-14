#!/bin/bash

# Script de inicialização do backend
# Este script ajuda a configurar o ambiente do backend pela primeira vez

echo "🚀 Configurando o backend do AI Email Sorter..."

# Verificar se o Python está instalado
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 não encontrado. Por favor, instale o Python 3."
    exit 1
fi

# Verificar se o Redis está rodando
if ! redis-cli ping &> /dev/null; then
    echo "⚠️  Redis não está rodando. Por favor, inicie o Redis antes de continuar."
    echo "   No macOS: brew services start redis"
    echo "   Ou execute: redis-server"
    exit 1
fi

# Criar ambiente virtual se não existir
if [ ! -d "venv" ]; then
    echo "📦 Criando ambiente virtual..."
    python3 -m venv venv
fi

# Ativar ambiente virtual
echo "🔌 Ativando ambiente virtual..."
source venv/bin/activate

# Instalar dependências
echo "📥 Instalando dependências..."
pip install -r requirements.txt

# Criar arquivo .env se não existir
if [ ! -f ".env" ]; then
    echo "📝 Criando arquivo .env a partir do env.example..."
    cp env.example .env
    echo "⚠️  IMPORTANTE: Edite o arquivo .env com suas configurações antes de continuar!"
    echo "   Especialmente:"
    echo "   - DJANGO_SECRET_KEY"
    echo "   - SOCIAL_AUTH_GOOGLE_OAUTH2_KEY"
    echo "   - SOCIAL_AUTH_GOOGLE_OAUTH2_SECRET"
    echo "   - GCLOUD_PROJECT"
    echo "   - PUBSUB_SUBSCRIPTION_ID"
    echo "   - GMAIL_PUBSUB_TOPIC"
    read -p "Pressione Enter após editar o arquivo .env..."
fi

# Gerar secret key se não estiver configurado
if grep -q "your-secret-key-here" .env 2>/dev/null; then
    echo "🔑 Gerando DJANGO_SECRET_KEY..."
    SECRET_KEY=$(python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())")
    if [[ "$OSTYPE" == "darwin"* ]]; then
        # macOS
        sed -i '' "s/DJANGO_SECRET_KEY=your-secret-key-here/DJANGO_SECRET_KEY=$SECRET_KEY/" .env
    else
        # Linux
        sed -i "s/DJANGO_SECRET_KEY=your-secret-key-here/DJANGO_SECRET_KEY=$SECRET_KEY/" .env
    fi
    echo "✅ DJANGO_SECRET_KEY gerado automaticamente"
fi

# Executar migrações
echo "🗄️  Executando migrações do banco de dados..."
python manage.py migrate

echo ""
echo "✅ Configuração do backend concluída!"
echo ""
echo "⚠️  IMPORTANTE: Sempre ative o ambiente virtual antes de rodar comandos do backend!"
echo "   Execute: source venv/bin/activate"
echo ""
echo "📋 Próximos passos:"
echo "   1. Certifique-se de que o Redis está rodando"
echo "   2. Em um terminal, execute:"
echo "      cd ai-email-sorter-backend"
echo "      source venv/bin/activate"
echo "      celery -A backend worker --loglevel=info"
echo "   3. Em outro terminal, execute:"
echo "      cd ai-email-sorter-backend"
echo "      source venv/bin/activate"
echo "      celery -A backend beat --loglevel=info"
echo "   4. Em outro terminal, execute:"
echo "      cd ai-email-sorter-backend"
echo "      source venv/bin/activate"
echo "      python manage.py runserver"
echo ""

