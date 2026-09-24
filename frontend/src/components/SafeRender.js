import React from "react";

/**
 * Componente que renderiza qualquer valor de forma segura
 * Previne erro "Objects are not valid as a React child"
 */
export const SafeRender = ({ value, fallback = null }) => {
  // Null/undefined
  if (value == null) return fallback;

  // Primitivos (string, number, boolean)
  if (typeof value !== "object") {
    return <>{String(value)}</>;
  }

  // Arrays
  if (Array.isArray(value)) {
    return (
      <div className="space-y-1">
        {value.map((item, idx) => (
          <SafeRender key={idx} value={item} />
        ))}
      </div>
    );
  }

  // Objetos - mostrar como JSON formatado em dev
  if (import.meta.env.DEV) {
    return (
      <pre className="text-xs bg-muted p-2 rounded overflow-auto max-h-32">
        {JSON.stringify(value, null, 2)}
      </pre>
    );
  }

  // Em produção, extrair mensagem ou mostrar tipo
  if (value.msg) return <>{String(value.msg)}</>;
  if (value.message) return <>{String(value.message)}</>;
  if (value.detail) return <SafeRender value={value.detail} />;

  return <span className="text-muted-foreground text-xs">[Objeto]</span>;
};

export default SafeRender;
