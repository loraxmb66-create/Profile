/**
 * Telegram bot sử dụng Google AI Studio (Gemini) để trả lời tin nhắn.
 *
 * Cài đặt phụ thuộc:
 *   npm install node-telegram-bot-api @google/generative-ai
 *
 * Cấu hình thông qua biến môi trường:
 *   TELEGRAM_BOT_TOKEN  – mã token bot Telegram
 *   GOOGLE_API_KEY      – API key của Google AI Studio (Gemini)
 *   GOOGLE_MODEL        – (tuỳ chọn) tên model, mặc định "gemini-1.5-flash"
 *
 * Chạy:
 *   node telegram_bot.js
 */

const TelegramBot = require('node-telegram-bot-api');
const { GoogleGenerativeAI } = require('@google/generative-ai');

const REQUIRED_ENV_VARS = {
  TELEGRAM_BOT_TOKEN: 'Token bot Telegram lấy từ @BotFather.',
  GOOGLE_API_KEY: 'API key tạo tại https://aistudio.google.com/app/apikey.',
};

function ensureRequiredEnv() {
  const missing = [];
  const values = {};

  for (const [name, description] of Object.entries(REQUIRED_ENV_VARS)) {
    const value = process.env[name];
    if (value && value.trim()) {
      values[name] = value.trim();
    } else {
      missing.push(`  • ${name}: ${description}`);
    }
  }

  if (missing.length > 0) {
    const help = [
      'Thiếu biến môi trường bắt buộc:',
      ...missing,
      '',
      'Cách thiết lập tạm thời:',
      '  • Linux/macOS (bash): export TÊN=GIÁ_TRỊ',
      '  • Windows (cmd):     set TÊN=GIÁ_TRỊ',
      '  • Windows (PowerShell): $Env:TÊN="GIÁ_TRỊ"',
      '',
      'Sau đó chạy lại: node telegram_bot.js',
    ].join('\n');
    throw new Error(help);
  }

  return values;
}

function initGemini(apiKey, modelName) {
  const genAI = new GoogleGenerativeAI(apiKey);
  return genAI.getGenerativeModel({ model: modelName });
}

function extractText(response) {
  if (!response) {
    return 'Không nhận được phản hồi từ Gemini.';
  }

  try {
    if (typeof response.response?.text === 'function') {
      const text = response.response.text();
      if (text && text.trim()) {
        return text.trim();
      }
    }

    const candidates = response.response?.candidates || response.candidates;
    if (Array.isArray(candidates)) {
      for (const candidate of candidates) {
        const parts = candidate?.content?.parts;
        if (Array.isArray(parts)) {
          const joined = parts
            .map((part) => {
              if (typeof part === 'string') return part;
              if (typeof part?.text === 'string') return part.text;
              return undefined;
            })
            .filter(Boolean)
            .join('\n');
          if (joined.trim()) {
            return joined.trim();
          }
        }
      }
    }
  } catch (error) {
    console.error('Không phân tích được phản hồi Gemini', error);
  }

  return typeof response === 'string' ? response : JSON.stringify(response, null, 2);
}

async function main() {
  const env = ensureRequiredEnv();
  const token = env.TELEGRAM_BOT_TOKEN;
  const modelName = process.env.GOOGLE_MODEL?.trim() || 'gemini-1.5-flash';
  const model = initGemini(env.GOOGLE_API_KEY, modelName);

  console.log(`Sử dụng model Gemini: ${modelName}`);

  const bot = new TelegramBot(token, { polling: true });
  console.log('Bot đã sẵn sàng và bắt đầu polling...');

  bot.on('polling_error', (error) => {
    console.error('Lỗi polling', error);
  });

  bot.onText(/^\/start\b/i, async (msg) => {
    const chatId = msg.chat.id;
    await bot.sendMessage(
      chatId,
      'Xin chào! Gửi cho tôi câu hỏi của bạn và tôi sẽ hỏi Google AI Studio (Gemini) giúp bạn.'
    );
  });

  bot.on('message', async (msg) => {
    if (!msg || !msg.text) {
      return;
    }

    const text = msg.text.trim();

    // Bỏ qua các command khác ngoài /start
    if (!text || (text.startsWith('/') && !text.toLowerCase().startsWith('/start'))) {
      return;
    }

    try {
      console.log('Gửi yêu cầu tới Gemini:', text);
      const response = await model.generateContent(text);
      const reply = extractText(response);
      await bot.sendMessage(msg.chat.id, reply, {
        reply_to_message_id: msg.message_id,
      });
    } catch (error) {
      console.error('Lỗi gọi Gemini', error);
      await bot.sendMessage(
        msg.chat.id,
        'Xin lỗi, tôi không thể liên hệ với Google AI Studio ngay lúc này. Vui lòng thử lại sau.',
        { reply_to_message_id: msg.message_id }
      );
    }
  });

  let isShuttingDown = false;
  const shutdown = () => {
    if (isShuttingDown) {
      return;
    }
    isShuttingDown = true;
    console.log('\nĐang dừng bot...');
    bot
      .stopPolling()
      .then(() => process.exit(0))
      .catch((error) => {
        console.error('Lỗi khi dừng bot', error);
        process.exit(1);
      });
  };

  process.once('SIGINT', shutdown);
  process.once('SIGTERM', shutdown);
}

main().catch((error) => {
  console.error(error.message || error);
  process.exit(1);
});
