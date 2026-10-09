import { Badge } from "@/components/ui/badge";

const LABELS = {
  id: "Identificador", key: "Chave", codigo: "Código", codigoItem: "Código do item",
  cliente: "Cliente", clienteNome: "Cliente", clientName: "Cliente", fornecedor: "Fornecedor",
  criadoEm: "Criado em", createdAt: "Criado em", atualizadoEm: "Atualizado em", updatedAt: "Atualizado em",
  criadoPor: "Criado por", createdBy: "Criado por", data: "Data", dataFabricacao: "Data de fabricação",
  dataValidade: "Data de validade", descricao: "Descrição", itemNome: "Item", nome: "Nome",
  nomeItem: "Item", quantidade: "Quantidade", qtd: "Quantidade", unidade: "Unidade",
  status: "Status", lote: "Lote", loteOrigem: "Lote de origem", op: "Ordem de produção",
  opKey: "Chave da OP", itens: "Itens", items: "Itens", caixasFechadas: "Caixas fechadas",
  caixasAbertas: "Caixas abertas", identificadorPalete: "Identificador do palete",
  origemRef: "Origem", observacoes: "Observações", observacao: "Observação", transportadora: "Transportadora",
  numeroNota: "Número da nota", numeroNf: "Número da NF", chaveNfe: "Chave da NF-e",
  endereco: "Endereço", cidade: "Cidade", estado: "Estado", uf: "UF", cep: "CEP",
  telefone: "Telefone", email: "E-mail", cnpj: "CNPJ", cpf: "CPF", sku: "SKU",
  produto: "Produto", produtoNome: "Produto", valor: "Valor", valorTotal: "Valor total",
  preco: "Preço", precoUnitario: "Preço unitário", peso: "Peso", pesoLiquido: "Peso líquido",
  pesoBruto: "Peso bruto", volume: "Volume", volumes: "Volumes", ativo: "Ativo",
  aprovado: "Aprovado", concluido: "Concluído", cancelado: "Cancelado", legado: "Registro legado",
};

const TECHNICAL_FIELDS = new Set(["_id", "tenant_id", "tenantId", "_migration"]);

function labelFor(key) {
  if (LABELS[key]) return LABELS[key];
  const spaced = String(key)
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .replaceAll("_", " ")
    .replaceAll("-", " ")
    .trim();
  return spaced ? spaced.charAt(0).toUpperCase() + spaced.slice(1) : "Campo";
}

function isEmpty(value) {
  return value == null || value === "";
}

function isObject(value) {
  return value != null && typeof value === "object" && !Array.isArray(value);
}

function looksLikeDate(key, value) {
  if (typeof value !== "string") return false;
  return /(data|date|em$|at$|created|updated|fabricacao|validade)/i.test(key)
    && /^\d{4}-\d{2}-\d{2}/.test(value);
}

function displayDate(value) {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  const hasTime = String(value).includes("T");
  return hasTime ? parsed.toLocaleString("pt-BR") : parsed.toLocaleDateString("pt-BR", { timeZone: "UTC" });
}

function PrimitiveValue({ fieldKey, value }) {
  if (isEmpty(value)) return <span className="italic text-muted-foreground">Não informado</span>;
  if (typeof value === "boolean") {
    return <Badge className={value ? "bg-emerald-100 text-emerald-700 hover:bg-emerald-100" : "bg-red-100 text-red-700 hover:bg-red-100"}>{value ? "Sim" : "Não"}</Badge>;
  }
  if (looksLikeDate(fieldKey, value)) return <span>{displayDate(value)}</span>;
  if (typeof value === "number") return <span className="tabular-nums">{value.toLocaleString("pt-BR")}</span>;
  if (/^https?:\/\//i.test(String(value))) return <a className="break-all text-primary underline" href={String(value)} target="_blank" rel="noreferrer">Abrir endereço</a>;
  return <span className="break-words whitespace-pre-wrap">{String(value)}</span>;
}

function Field({ fieldKey, value }) {
  return (
    <div className="min-w-0 rounded-lg border bg-card/60 p-3">
      <p className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">{labelFor(fieldKey)}</p>
      <div className="text-sm font-medium text-foreground"><PrimitiveValue fieldKey={fieldKey} value={value} /></div>
    </div>
  );
}

function PrimitiveList({ fieldKey, values }) {
  return (
    <section className="rounded-xl border bg-muted/20 p-4">
      <h4 className="mb-3 text-sm font-semibold">{labelFor(fieldKey)}</h4>
      <div className="flex flex-wrap gap-2">
        {values.length ? values.map((value, index) => <Badge key={`${fieldKey}-${index}`} variant="outline"><PrimitiveValue fieldKey={fieldKey} value={value} /></Badge>) : <span className="text-sm italic text-muted-foreground">Nenhum registro</span>}
      </div>
    </section>
  );
}

function ObjectCard({ title, value, depth }) {
  const primitiveEntries = Object.entries(value || {}).filter(([key, item]) => !TECHNICAL_FIELDS.has(key) && !isObject(item) && !Array.isArray(item));
  const nestedEntries = Object.entries(value || {}).filter(([key, item]) => !TECHNICAL_FIELDS.has(key) && (isObject(item) || Array.isArray(item)));
  return (
    <div className="rounded-xl border bg-card p-4 shadow-sm">
      {title && <h5 className="mb-3 border-b pb-2 text-sm font-semibold">{title}</h5>}
      {primitiveEntries.length > 0 && <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">{primitiveEntries.map(([key, item]) => <Field key={key} fieldKey={key} value={item} />)}</div>}
      {nestedEntries.length > 0 && <div className="mt-4 space-y-3">{nestedEntries.map(([key, item]) => <StructuredValue key={key} fieldKey={key} value={item} depth={depth + 1} />)}</div>}
      {!primitiveEntries.length && !nestedEntries.length && <p className="text-sm italic text-muted-foreground">Nenhuma informação preenchida</p>}
    </div>
  );
}

function ObjectCollection({ fieldKey, entries, depth }) {
  return (
    <section className="rounded-xl border bg-muted/20 p-4">
      <div className="mb-3 flex items-center justify-between gap-3">
        <h4 className="text-sm font-semibold">{labelFor(fieldKey)}</h4>
        <Badge variant="secondary">{entries.length} registro(s)</Badge>
      </div>
      <div className="space-y-3">
        {entries.map(([key, item], index) => (
          <ObjectCard key={`${fieldKey}-${key}-${index}`} title={item?.itemNome || item?.nome || item?.descricao || `${labelFor(fieldKey)} ${index + 1}`} value={{ referencia: key, ...item }} depth={depth} />
        ))}
      </div>
    </section>
  );
}

function StructuredValue({ fieldKey, value, depth = 0 }) {
  if (depth > 6) return <Field fieldKey={fieldKey} value="Conteúdo disponível em nível técnico" />;
  if (Array.isArray(value)) {
    if (!value.some(isObject)) return <PrimitiveList fieldKey={fieldKey} values={value} />;
    return <ObjectCollection fieldKey={fieldKey} entries={value.map((item, index) => [String(index + 1), isObject(item) ? item : { valor: item }])} depth={depth} />;
  }
  if (isObject(value)) {
    const entries = Object.entries(value);
    if (entries.length > 0 && entries.every(([, item]) => isObject(item))) return <ObjectCollection fieldKey={fieldKey} entries={entries} depth={depth} />;
    return <section><h4 className="mb-2 text-sm font-semibold">{labelFor(fieldKey)}</h4><ObjectCard value={value} depth={depth} /></section>;
  }
  return <Field fieldKey={fieldKey} value={value} />;
}

export default function LegacyStructuredFields({ data }) {
  if (!data || !isObject(data)) return <div className="rounded-lg border p-4 text-sm text-muted-foreground">Nenhum dado disponível na origem.</div>;
  const primitiveEntries = Object.entries(data).filter(([key, value]) => !TECHNICAL_FIELDS.has(key) && !isObject(value) && !Array.isArray(value));
  const structuredEntries = Object.entries(data).filter(([key, value]) => !TECHNICAL_FIELDS.has(key) && (isObject(value) || Array.isArray(value)));
  return (
    <div className="space-y-4">
      {primitiveEntries.length > 0 && <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">{primitiveEntries.map(([key, value]) => <Field key={key} fieldKey={key} value={value} />)}</div>}
      {structuredEntries.map(([key, value]) => <StructuredValue key={key} fieldKey={key} value={value} />)}
    </div>
  );
}

export { labelFor };
