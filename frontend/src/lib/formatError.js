/**
 * Formata qualquer tipo de erro para string renderizável
 * @param {any} error - Erro de qualquer tipo
 * @returns {string} String formatada para exibição
 */
export function formatError(error) {
  if (!error) return "Erro desconhecido";

  // String já formatada
  if (typeof error === "string") return error;

  // Erro de validação do backend (Pydantic/FastAPI)
  if (error.msg) return error.msg;

  // Erro JavaScript padrão
  if (error.message) return error.message;

  // Erro de API com detail
  if (error.detail) {
    // Se detail for string
    if (typeof error.detail === "string") return error.detail;
    // Se detail for array de erros de validação
    if (Array.isArray(error.detail)) {
      return error.detail.map(e => e.msg || JSON.stringify(e)).join(", ");
    }
    if (typeof error.detail.message === "string") {
      const details = [
        ...(Array.isArray(error.detail.bloqueios) ? error.detail.bloqueios : []),
        ...(Array.isArray(error.detail.alertas) ? error.detail.alertas : []),
      ].filter(Boolean).map(String);
      return [error.detail.message, ...details].join(" ");
    }
    return JSON.stringify(error.detail);
  }

  // Último recurso: stringify
  try {
    return JSON.stringify(error);
  } catch {
    return "Erro ao processar mensagem de erro";
  }
}

/**
 * Extrai mensagem de erro de resposta Axios
 * @param {any} error - Erro do Axios
 * @returns {string} Mensagem de erro formatada
 */
export function formatApiError(error) {
  // Erro de resposta HTTP
  if (error.response?.data) {
    return formatError(error.response.data);
  }

  // Erro de rede
  if (error.request) {
    return "Erro de conexão com o servidor";
  }

  // Erro genérico
  return formatError(error);
}
