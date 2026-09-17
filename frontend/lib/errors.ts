/**
 * Unified error code → human-readable text mapping.
 *
 * Every error shown to the user MUST go through `friendlyError()` which
 * extracts the best available text and falls back to the DEFAULT message.
 * Technical details (objects, stacks, raw codes) are logged to console
 * but never rendered in the UI.
 */

/* ------------------------------------------------------------------ */
/*  Translation maps (RU primary — the app is Russian-first)          */
/* ------------------------------------------------------------------ */

type ErrorEntry = string | ((field?: string) => string);

const ERROR_MESSAGES_RU: Record<string, ErrorEntry> = {
  FIELD_REQUIRED: (field) => `Поле «${field || 'обязательное'}» обязательно для заполнения`,
  INVALID_FORMAT: (field) => `Проверьте правильность заполнения поля «${field || 'данные'}»`,
  INVALID_EMAIL: () => 'Введите корректный email',
  INVALID_PHONE: () => 'Номер телефона указан в неверном формате',
  PASSWORD_TOO_SHORT: () => 'Пароль должен содержать минимум 8 символов',
  ALREADY_EXISTS: () => 'Такие данные уже существуют в системе',
  ALREADY_REGISTERED: () => 'Пользователь с таким email уже зарегистрирован',
  WRONG_PASSWORD: () => 'Неверный email или пароль',
  INVALID_CREDENTIALS: () => 'Неверный логин или пароль',
  ACCOUNT_DISABLED: () => 'Учётная запись заблокирована',
  UNAUTHORIZED: () => 'Требуется авторизация',
  FORBIDDEN: () => 'Недостаточно прав для выполнения действия',
  NOT_FOUND: () => 'Запрашиваемый ресурс не найден',
  RATE_LIMITED: () => 'Слишком много попыток. Подождите немного и попробуйте снова',
  SERVER_ERROR: () => 'Произошла ошибка сервера. Попробуйте ещё раз позже',
  NETWORK_ERROR: () => 'Не удалось подключиться к серверу. Проверьте подключение к интернету',
  TIMEOUT: () => 'Превышено время ожидания. Попробуйте ещё раз',
  DEFAULT: () => 'Что-то пошло не так. Попробуйте ещё раз',
};

const ERROR_MESSAGES_EN: Record<string, ErrorEntry> = {
  FIELD_REQUIRED: (field) => `Field "${field || 'this field'}" is required`,
  INVALID_FORMAT: (field) => `Please check the format of "${field || 'this field'}"`,
  INVALID_EMAIL: () => 'Please enter a valid email address',
  INVALID_PHONE: () => 'Invalid phone number format',
  PASSWORD_TOO_SHORT: () => 'Password must be at least 8 characters',
  ALREADY_EXISTS: () => 'This data already exists',
  ALREADY_REGISTERED: () => 'A user with this email is already registered',
  WRONG_PASSWORD: () => 'Incorrect email or password',
  INVALID_CREDENTIALS: () => 'Invalid username or password',
  ACCOUNT_DISABLED: () => 'This account has been disabled',
  UNAUTHORIZED: () => 'Authorization required',
  FORBIDDEN: () => 'You do not have permission to perform this action',
  NOT_FOUND: () => 'The requested resource was not found',
  RATE_LIMITED: () => 'Too many attempts. Please wait a moment and try again',
  SERVER_ERROR: () => 'A server error occurred. Please try again later',
  NETWORK_ERROR: () => 'Could not connect to the server. Check your internet connection',
  TIMEOUT: () => 'Request timed out. Please try again',
  DEFAULT: () => 'Something went wrong. Please try again',
};

/* ------------------------------------------------------------------ */
/*  Helpers                                                           */
/* ------------------------------------------------------------------ */

function resolveEntry(entry: ErrorEntry, field?: string): string {
  return typeof entry === 'function' ? entry(field) : entry;
}

/* ------------------------------------------------------------------ */
/*  Get current locale                                                */
/* ------------------------------------------------------------------ */

function getLocale(): string {
  if (typeof window === 'undefined') return 'ru';
  return localStorage.getItem('storywatcher_lang') || 'ru';
}

function getMessages(): Record<string, ErrorEntry> {
  return getLocale() === 'en' ? ERROR_MESSAGES_EN : ERROR_MESSAGES_RU;
}

/* ------------------------------------------------------------------ */
/*  Error code detection from various error shapes                    */
/* ------------------------------------------------------------------ */

/** Known backend error detail patterns → our error codes */
const DETAIL_PATTERNS: [RegExp, string][] = [
  [/already registered/i, 'ALREADY_REGISTERED'],
  [/already.*exist/i, 'ALREADY_EXISTS'],
  [/invalid.*email|некорректный.*email/i, 'INVALID_EMAIL'],
  [/invalid.*phone|неверный.*номер/i, 'INVALID_PHONE'],
  [/password.*8.*символ|password.*min/i, 'PASSWORD_TOO_SHORT'],
  [/неверный.*пароль|invalid.*password|wrong.*password/i, 'WRONG_PASSWORD'],
  [/неверный.*email|incorrect.*email/i, 'WRONG_PASSWORD'],
  [/invalid.*credentials/i, 'INVALID_CREDENTIALS'],
  [/disabled/i, 'ACCOUNT_DISABLED'],
  [/flood.*wait|too many|слишком.*много/i, 'RATE_LIMITED'],
  [/unauthorized|не.*авториз/i, 'UNAUTHORIZED'],
  [/forbidden|доступ.*запрещ/i, 'FORBIDDEN'],
  [/not.*found|не.*найден/i, 'NOT_FOUND'],
  [/session finalize failed/i, 'SERVER_ERROR'],
  [/failed.*send.*code/i, 'SERVER_ERROR'],
  [/confirmation failed/i, 'SERVER_ERROR'],
  [/password confirmation failed/i, 'SERVER_ERROR'],
];

function detectErrorCode(message: string): string | null {
  for (const [pattern, code] of DETAIL_PATTERNS) {
    if (pattern.test(message)) return code;
  }
  return null;
}

/* ------------------------------------------------------------------ */
/*  Public API                                                        */
/* ------------------------------------------------------------------ */

/**
 * Convert any error (object, string, unknown) into a user-friendly
 * string. Technical details are logged to console.
 *
 * Usage:
 *   } catch (e) {
 *     setError(friendlyError(e));
 *   }
 */
export function friendlyError(e: unknown): string {
  // Log the full technical error for developers
  if (e instanceof Error) {
    console.error('[Error]', e.message, e.stack);
  } else if (typeof e === 'object' && e !== null) {
    console.error('[Error object]', e);
  } else {
    console.error('[Error]', e);
  }

  const messages = getMessages();

  // Extract the raw message from various error shapes
  let rawMessage = '';
  let rawCode: string | undefined;

  if (e && typeof e === 'object') {
    const obj = e as Record<string, unknown>;

    // ApiError has .message and .status
    if (typeof obj.message === 'string') {
      rawMessage = obj.message;
    }

    // FastAPI detail might be nested
    if (typeof obj.detail === 'string') {
      rawMessage = rawMessage || obj.detail;
    } else if (typeof obj.detail === 'object' && obj.detail !== null) {
      const detail = obj.detail as Record<string, unknown>;
      if (typeof detail.message === 'string') rawMessage = detail.message;
      if (typeof detail.code === 'string') rawCode = detail.code;
    }

    // Network errors
    if (obj.name === 'TypeError' && typeof obj.message === 'string' && /fetch|network/i.test(obj.message)) {
      return resolveEntry(messages.NETWORK_ERROR);
    }
    if (obj.name === 'AbortError') {
      return resolveEntry(messages.TIMEOUT);
    }
  } else if (typeof e === 'string') {
    rawMessage = e;
  }

  // If we got nothing useful
  if (!rawMessage) {
    return resolveEntry(messages.DEFAULT);
  }

  // Try to detect an error code from the message text
  const detectedCode = rawCode || detectErrorCode(rawMessage);
  if (detectedCode && messages[detectedCode]) {
    return resolveEntry(messages[detectedCode]);
  }

  // If the message itself is a clear, human-readable string, use it directly
  // (many backend errors are already in plain Russian/English)
  if (rawMessage.length > 3 && rawMessage.length < 500 && !/^\[object|undefined|null|Error/i.test(rawMessage)) {
    return rawMessage;
  }

  return resolveEntry(messages.DEFAULT);
}

/**
 * Map a specific field validation error.
 */
export function fieldError(field: string | null, code: string = 'FIELD_REQUIRED'): string {
  const messages = getMessages();
  const handler = messages[code] || messages.DEFAULT;
  return resolveEntry(handler, field || undefined);
}

/**
 * Simple inline validation for required fields.
 * Returns null if valid, error message if invalid.
 */
export function validateRequired(value: string, fieldName: string): string | null {
  if (!value || !value.trim()) {
    return fieldError(fieldName, 'FIELD_REQUIRED');
  }
  return null;
}

export function validateEmail(value: string): string | null {
  if (!value || !value.trim()) {
    return fieldError('Email', 'FIELD_REQUIRED');
  }
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value)) {
    return fieldError('email', 'INVALID_EMAIL');
  }
  return null;
}

export function validatePassword(value: string): string | null {
  if (!value) {
    return fieldError('Пароль', 'FIELD_REQUIRED');
  }
  if (value.length < 8) {
    return fieldError('Пароль', 'PASSWORD_TOO_SHORT');
  }
  return null;
}

export function validatePhone(value: string): string | null {
  if (!value || !value.trim()) {
    return fieldError('Телефон', 'FIELD_REQUIRED');
  }
  if (value.trim().length < 5) {
    return fieldError('Телефон', 'INVALID_PHONE');
  }
  return null;
}
