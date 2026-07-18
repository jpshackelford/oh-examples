#!/bin/bash
# Sandbox initialization script for warm pool
# This demonstrates the preparation steps needed to make a sandbox ready for use
# In a production deployment, you would replace this with your actual application setup

set -e  # Exit on error

echo "🚀 Starting sandbox initialization..."
echo "📦 Sandbox ID: ${SANDBOX_ID:-unknown}"

# 1. Install Ruby (using system package manager for speed in this demo)
echo "📥 Installing Ruby..."
apt-get update -qq
apt-get install -y -qq ruby-full ruby-dev build-essential > /dev/null 2>&1
ruby --version

# 2. Install Sinatra gem
echo "💎 Installing Sinatra gem..."
gem install sinatra --no-document > /dev/null 2>&1

# 3. Create service directory
echo "📁 Setting up service directory..."
mkdir -p /workspace/services
cd /workspace/services

# 4. Copy the quote service (in production, this would be your actual app)
echo "📝 Deploying quote service..."
cat > /workspace/services/quote_service.rb << 'RUBY_SERVICE_EOF'
#!/usr/bin/env ruby
# frozen_string_literal: true

require 'sinatra'
require 'json'

set :port, 4567
set :bind, '0.0.0.0'

QUOTES = [
  { author: 'Alan Kay', text: 'The best way to predict the future is to invent it.' },
  { author: 'Donald Knuth', text: 'Premature optimization is the root of all evil.' },
  { author: 'Rob Pike', text: 'Simplicity is complicated.' },
  { author: 'Ken Thompson', text: 'When in doubt, use brute force.' },
  { author: 'Yukihiro Matsumoto', text: 'Ruby is designed to make programmers happy.' },
  { author: 'David Heinemeier Hansson', text: 'Convention over configuration.' },
  { author: 'Sandi Metz', text: 'Duplication is far cheaper than the wrong abstraction.' },
  { author: 'Martin Fowler', text: 'Any fool can write code that a computer can understand. Good programmers write code that humans can understand.' }
].freeze

get '/health' do
  content_type :json
  { status: 'ok', service: 'quote_service', version: '1.0.0' }.to_json
end

get '/quote' do
  content_type :json
  quote = QUOTES.sample
  { quote: quote[:text], author: quote[:author], timestamp: Time.now.iso8601 }.to_json
end

get '/quotes' do
  content_type :json
  { quotes: QUOTES, count: QUOTES.size }.to_json
end

get '/quotes/:author' do
  content_type :json
  author_param = params['author'].downcase
  matches = QUOTES.select { |q| q[:author].downcase.include?(author_param) }
  if matches.empty?
    status 404
    { error: 'No quotes found for that author' }.to_json
  else
    { quotes: matches, count: matches.size }.to_json
  end
end

get '/' do
  content_type :json
  {
    service: 'Quote of the Day API',
    version: '1.0.0',
    endpoints: { health: 'GET /health', random_quote: 'GET /quote', all_quotes: 'GET /quotes', by_author: 'GET /quotes/:author' },
    sandbox_id: ENV['SANDBOX_ID'] || 'unknown',
    message: 'This service demonstrates a pre-initialized Ruby application in a warm sandbox. In production, this would be your actual application service.'
  }.to_json
end
RUBY_SERVICE_EOF

chmod +x /workspace/services/quote_service.rb

# 5. Start the service in background
echo "🌐 Starting quote service on port 4567..."
cd /workspace/services
nohup ruby quote_service.rb > /tmp/quote_service.log 2>&1 &
SERVICE_PID=$!
echo "Service PID: $SERVICE_PID"

# 6. Wait for service to be ready (with timeout)
echo "⏳ Waiting for service to respond..."
TIMEOUT=30
ELAPSED=0
while [ $ELAPSED -lt $TIMEOUT ]; do
    if curl -sf http://localhost:4567/health > /dev/null 2>&1; then
        echo "✅ Service is healthy!"
        curl -s http://localhost:4567/health | jq . || true
        break
    fi
    sleep 1
    ELAPSED=$((ELAPSED + 1))
done

if [ $ELAPSED -ge $TIMEOUT ]; then
    echo "❌ Service failed to start within ${TIMEOUT}s"
    echo "Service log:"
    cat /tmp/quote_service.log
    exit 1
fi

# 7. Final verification - test the main endpoint
echo "🧪 Testing service endpoint..."
QUOTE_RESPONSE=$(curl -s http://localhost:4567/quote)
echo "Sample quote: $QUOTE_RESPONSE"

# 8. Create a marker file to indicate successful initialization
echo "✅ Creating ready marker..."
echo "$(date -Iseconds)" > /workspace/.sandbox_ready
echo "SANDBOX_ID=${SANDBOX_ID:-unknown}" >> /workspace/.sandbox_ready
echo "SERVICE_PID=$SERVICE_PID" >> /workspace/.sandbox_ready
echo "RUBY_VERSION=$(ruby --version)" >> /workspace/.sandbox_ready

echo ""
echo "🎉 Sandbox initialization complete!"
echo "📊 Summary:"
echo "   - Ruby: $(ruby --version | cut -d' ' -f2)"
echo "   - Sinatra: installed"
echo "   - Quote Service: running on port 4567 (PID $SERVICE_PID)"
echo "   - Status: READY"
echo ""
echo "💡 In production, replace this initialization with your application-specific setup"
