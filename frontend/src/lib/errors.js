const MESSAGES = {
  network_error: 'Can’t reach the Synchronik AI service. Check your connection or try again shortly.',
  backend_unavailable: 'The assistant service is unavailable right now. Please try again shortly.',
  llm_unavailable: 'The answer engine is temporarily unavailable. Please try again in a moment.',
  llm_not_configured: 'The answer engine isn’t configured on the server yet. Please contact your administrator.',
  database_unavailable: 'The knowledge database is temporarily unavailable. Please try again shortly.',
  rate_limited: 'You’re sending requests too quickly. Please wait a moment and retry.',
  file_too_large: 'That file is too large to upload.',
  unsupported_file: 'That file type isn’t supported.',
  timeout: 'The request took too long. Please try again.',
  unauthorized: 'The admin key was rejected. Please enter it again on the Knowledge Base page.',
  not_found: 'That item could not be found. It may have been deleted.',
  validation_error: 'The request was not valid. Please check your input.',
  malformed_response: 'The server sent an unexpected response. Please try again.',
  internal_error: 'Something went wrong on our side. Please try again.',
}

export function friendlyError(err) {
  if (!err) return MESSAGES.internal_error
  return MESSAGES[err.code] || MESSAGES.internal_error
}

const NON_RETRYABLE = ['llm_not_configured', 'unauthorized', 'unsupported_file', 'file_too_large', 'validation_error']
export const isRetryable = (err) => !NON_RETRYABLE.includes(err && err.code)
