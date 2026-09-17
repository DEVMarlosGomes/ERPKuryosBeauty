import { Plus, RotateCcw, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";

const BLOCO2_COMPONENTS = [
  ["frasco_pote_bisnaga", "Frasco / pote / bisnaga"],
  ["airless_rollon_ampola", "Airless / roll-on / ampola"],
  ["tampa", "Tampa (rosca / flip-top / pressao)"],
  ["valvula_pump", "Valvula pump / bomba dosadora"],
  ["valvula_spray", "Valvula spray / atomizador"],
  ["valvula_aerossol_atuador", "Valvula aerossol + atuador"],
  ["gatilho_trigger", "Gatilho / trigger"],
  ["batoque_redutor_orificio", "Batoque / redutor / orificio"],
  ["lacre_inducao_disco", "Lacre de inducao / disco de vedacao"],
  ["aplicador", "Aplicador (pincel / espatula / esponja)"],
];

const BLOCO3_COMPONENTS = [
  ["rotulo", "Rotulo (frontal / contra)"],
  ["cartucho", "Cartucho"],
  ["bula_folheto", "Bula / folheto"],
  ["selo_lacre_seguranca", "Selo / lacre de seguranca"],
  ["celofane_shrink", "Celofane / shrink"],
  ["berco_suporte_interno", "Berco / suporte interno"],
];

const BLOCO4_COMPONENTS = [
  ["display_expositor_pdv", "Display / expositor de PDV"],
  ["caixa_master", "Caixa de embarque (master)"],
  ["divisoria_colmeia", "Divisoria / separador / colmeia"],
  ["cantoneira", "Cantoneira"],
  ["paletizacao", "Especificacao de paletizacao"],
];

function rows(seed, hasArt = false) {
  return seed.map(([id, componente]) => ({
    id,
    componente,
    aplicavel: "",
    definido: "",
    fornecido_por: "",
    ...(hasArt ? { arte_cria_aprova: "", arte_aprovada: "" } : { especificacao_fornecedor_codigo: "" }),
    observacoes: "",
  }));
}

function normalizeBinary(value) {
  if (value === true) return "sim";
  if (value === false || value == null) return "nao";
  const normalized = String(value).trim().toLowerCase();
  if (["", "nao", "não", "n", "ñ", "false", "0", "off"].includes(normalized)) return "nao";
  return "sim";
}

function normalizeComponentRows(items, hasArt = false) {
  return (items || []).map((item) => ({
    ...item,
    aplicavel: normalizeBinary(item.aplicavel),
    definido: normalizeBinary(item.definido),
    ...(hasArt ? { arte_aprovada: normalizeBinary(item.arte_aprovada) } : {}),
  }));
}

export function emptyKickoffQuestionnaire() {
  return {
    schema_version: "questionario_composicao_projeto_2",
    bloco0: {
      cliente: "",
      nome_produto: "",
      categoria: "",
      categoria_outro: "",
      forma_fisica: "",
      forma_fisica_outro: "",
      volume_gramatura: "",
      numero_skus_variacoes: "",
      varia_entre_skus: [],
      varia_entre_skus_outro: "",
      unidades_por_display: "",
      displays_ou_unidades_por_caixa_master: "",
      registro_notificacao_anvisa: "",
      detentor_registro: "",
      responsavel_tecnico: "",
      modelo_servico: "",
    },
    bloco1: {
      formula: "",
      cliente_fornece: [],
      tem_cor: "",
      tem_brilho_mica_glitter: "",
      viscosidade: "",
      densidade: "",
      fragrancia_essencia: "",
      compra_fragrancia_por: "",
      observacoes_formulacao: "",
    },
    bloco2: { componentes: rows(BLOCO2_COMPONENTS) },
    bloco3: { componentes: rows(BLOCO3_COMPONENTS, true) },
    bloco4: { componentes: rows(BLOCO4_COMPONENTS) },
    bloco5: {
      especificacoes_cq_componentes: "",
      especificacoes_cq_anexos: [],
      testes_aprovacoes_obrigatorios: "",
      amostra_referencia_fornecida_cliente: "",
    },
    fechamento: {
      data_prevista_inicio_producao: "",
      volume_primeiro_lote: "",
      responsavel_kuryos: "",
      responsavel_cliente: "",
      data_preenchimento: "",
    },
    autopopulated_from: [],
  };
}

function mergeQuestionnaire(value) {
  const base = emptyKickoffQuestionnaire();
  const data = value || {};
  return {
    ...base,
    ...data,
    bloco0: { ...base.bloco0, ...(data.bloco0 || {}) },
    bloco1: {
      ...base.bloco1,
      ...(data.bloco1 || {}),
      tem_cor: normalizeBinary(data.bloco1?.tem_cor),
      tem_brilho_mica_glitter: normalizeBinary(data.bloco1?.tem_brilho_mica_glitter),
    },
    bloco2: { componentes: normalizeComponentRows(data.bloco2?.componentes?.length ? data.bloco2.componentes : base.bloco2.componentes) },
    bloco3: { componentes: normalizeComponentRows(data.bloco3?.componentes?.length ? data.bloco3.componentes : base.bloco3.componentes, true) },
    bloco4: { componentes: normalizeComponentRows(data.bloco4?.componentes?.length ? data.bloco4.componentes : base.bloco4.componentes) },
    bloco5: {
      ...base.bloco5,
      ...(data.bloco5 || {}),
      amostra_referencia_fornecida_cliente: normalizeBinary(data.bloco5?.amostra_referencia_fornecida_cliente),
    },
    fechamento: { ...base.fechamento, ...(data.fechamento || {}) },
  };
}

export function questionnaireFromKickoff(kickoff) {
  if (kickoff?.questionario_composicao) return mergeQuestionnaire(kickoff.questionario_composicao);
  const block1 = kickoff?.bloco1 || {};
  const block2 = kickoff?.bloco2 || {};
  const block3 = kickoff?.bloco3 || {};
  const block4 = kickoff?.bloco4 || {};
  const q = emptyKickoffQuestionnaire();
  q.bloco0.cliente = block1.cliente || "";
  q.bloco0.nome_produto = block3.nome_comercial_cliente || block3.nome_tecnico_produto || block1.projeto_vinculado || "";
  q.bloco0.categoria = block3.categoria_anvisa || block1.categoria_anvisa_herdada || "";
  q.bloco0.forma_fisica = block3.forma_apresentacao || "";
  q.bloco0.volume_gramatura = [block3.volume_peso_liquido_valor, block3.volume_peso_liquido_unidade].filter(Boolean).join(" ");
  q.bloco0.displays_ou_unidades_por_caixa_master = block2.quantidade_por_caixa || block4.caixa_master_unidades || "";
  q.bloco0.detentor_registro = block1.cliente || "";
  q.bloco0.responsavel_tecnico = block3.responsavel_liberacao_lote || "";
  q.bloco1.fragrancia_essencia = block3.odor || "";
  q.bloco1.tem_cor = block3.cor_descricao || "";
  q.bloco5.especificacoes_cq_componentes = block3.plano_amostragem || "";
  q.bloco5.testes_aprovacoes_obrigatorios = (block3.analises_obrigatorias_por_lote || []).join("\n");
  q.fechamento.data_prevista_inicio_producao = block2.data_entrega_contratada || "";
  q.fechamento.volume_primeiro_lote = block2.volume_primeiro_pedido || "";
  q.fechamento.responsavel_kuryos = block1.responsavel_comercial || "";
  q.fechamento.data_preenchimento = block1.data_abertura ? String(block1.data_abertura).slice(0, 10) : "";
  return q;
}

function Section({ title, children }) {
  return (
    <section className="rounded-md border border-border bg-card p-4 space-y-4">
      <h2 className="text-base font-semibold">{title}</h2>
      {children}
    </section>
  );
}

function Field({ label, value, onChange, type = "text", className = "" }) {
  return (
    <div className={className}>
      <Label>{label}</Label>
      <Input type={type} value={value || ""} onChange={(event) => onChange(event.target.value)} />
    </div>
  );
}

function TextField({ label, value, onChange, className = "", rows = 3 }) {
  return (
    <div className={className}>
      <Label>{label}</Label>
      <Textarea rows={rows} value={value || ""} onChange={(event) => onChange(event.target.value)} />
    </div>
  );
}

function YesNoToggle({ label, value, onChange, compact = false }) {
  const checked = normalizeBinary(value) === "sim";
  return (
    <div className={compact ? "flex items-center" : "space-y-2"}>
      {label && <Label>{label}</Label>}
      <div
        className={`inline-flex items-center gap-2 rounded-full border px-2.5 py-1.5 transition-colors ${checked
          ? "border-emerald-500/50 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
          : "border-red-500/50 bg-red-500/10 text-red-600 dark:text-red-400"
        }`}
      >
        <Switch
          checked={checked}
          onCheckedChange={(next) => onChange(next ? "sim" : "nao")}
          aria-label={label || "Alternar entre sim e nao"}
          className="data-[state=checked]:bg-emerald-500 data-[state=unchecked]:bg-red-500"
        />
        <span className="min-w-8 text-xs font-bold">{checked ? "SIM" : "NÃO"}</span>
      </div>
    </div>
  );
}

function ChoiceGroup({ label, value, onChange, options }) {
  return (
    <div className="space-y-2">
      <Label>{label}</Label>
      <div className="flex flex-wrap gap-2">
        {options.map((option) => (
          <button
            key={option.value}
            type="button"
            className={`rounded-md border px-3 py-1.5 text-sm ${value === option.value ? "border-primary bg-primary text-primary-foreground" : "border-border hover:bg-accent"}`}
            onClick={() => onChange(value === option.value ? "" : option.value)}
          >
            {option.label}
          </button>
        ))}
      </div>
    </div>
  );
}

function CheckboxGroup({ label, values = [], onChange, options }) {
  const current = Array.isArray(values) ? values : [];
  const toggle = (value) => {
    onChange(current.includes(value) ? current.filter((item) => item !== value) : [...current, value]);
  };
  return (
    <div className="space-y-2">
      <Label>{label}</Label>
      <div className="flex flex-wrap gap-2">
        {options.map((option) => (
          <button
            key={option.value}
            type="button"
            className={`rounded-md border px-3 py-1.5 text-sm ${current.includes(option.value) ? "border-primary bg-primary text-primary-foreground" : "border-border hover:bg-accent"}`}
            onClick={() => toggle(option.value)}
          >
            {option.label}
          </button>
        ))}
      </div>
    </div>
  );
}

function ComponentTable({ title, value, onChange, defaults, hasArt = false }) {
  const list = value?.componentes || [];
  const updateRow = (index, field, nextValue) => {
    const next = list.map((row, rowIndex) => rowIndex === index ? { ...row, [field]: nextValue } : row);
    onChange({ componentes: next });
  };
  const removeRow = (index) => onChange({ componentes: list.filter((_, rowIndex) => rowIndex !== index) });
  const clearRow = (index) => {
    const original = list[index] || {};
    const blank = {
      id: original.id,
      componente: original.componente,
      aplicavel: "",
      definido: "",
      fornecido_por: "",
      ...(hasArt ? { arte_cria_aprova: "", arte_aprovada: "" } : { especificacao_fornecedor_codigo: "" }),
      observacoes: "",
    };
    const next = list.map((row, rowIndex) => rowIndex === index ? blank : row);
    onChange({ componentes: next });
  };
  const addRow = () => {
    const id = `custom_${Date.now()}`;
    onChange({ componentes: [...list, { id, componente: "", aplicavel: "", definido: "", fornecido_por: "", ...(hasArt ? { arte_cria_aprova: "", arte_aprovada: "" } : { especificacao_fornecedor_codigo: "" }), observacoes: "" }] });
  };
  const restoreDefaults = () => onChange({ componentes: rows(defaults, hasArt) });

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-sm font-medium">{title}</h3>
        <div className="flex gap-2">
          <Button type="button" variant="outline" size="sm" onClick={restoreDefaults} className="gap-1.5">
            <RotateCcw className="h-3.5 w-3.5" />
            Restaurar
          </Button>
          <Button type="button" variant="outline" size="sm" onClick={addRow} className="gap-1.5">
            <Plus className="h-3.5 w-3.5" />
            Componente
          </Button>
        </div>
      </div>
      <div className="overflow-x-auto rounded-md border">
        <table className="w-full min-w-[980px] text-sm">
          <thead className="bg-muted/60">
            <tr>
              <th className="px-2 py-2 text-left font-medium">Componente</th>
              <th className="px-2 py-2 text-left font-medium">Aplicavel?</th>
              <th className="px-2 py-2 text-left font-medium">Definido?</th>
              <th className="px-2 py-2 text-left font-medium">Fornecido por</th>
              <th className="px-2 py-2 text-left font-medium">{hasArt ? "Arte: cria / aprova" : "Especificacao / Fornecedor / Codigo"}</th>
              {hasArt && <th className="px-2 py-2 text-left font-medium">Arte aprovada?</th>}
              <th className="px-2 py-2 text-left font-medium">Obs.</th>
              <th className="px-2 py-2" />
            </tr>
          </thead>
          <tbody className="divide-y">
            {list.map((row, index) => (
              <tr key={row.id || index}>
                <td className="px-2 py-2"><Input value={row.componente || ""} onChange={(event) => updateRow(index, "componente", event.target.value)} /></td>
                <td className="px-2 py-2"><YesNoToggle compact value={row.aplicavel} onChange={(next) => updateRow(index, "aplicavel", next)} /></td>
                <td className="px-2 py-2"><YesNoToggle compact value={row.definido} onChange={(next) => updateRow(index, "definido", next)} /></td>
                <td className="px-2 py-2"><Input value={row.fornecido_por || ""} onChange={(event) => updateRow(index, "fornecido_por", event.target.value)} /></td>
                <td className="px-2 py-2">
                  <Input
                    value={hasArt ? row.arte_cria_aprova || "" : row.especificacao_fornecedor_codigo || ""}
                    onChange={(event) => updateRow(index, hasArt ? "arte_cria_aprova" : "especificacao_fornecedor_codigo", event.target.value)}
                  />
                </td>
                {hasArt && <td className="px-2 py-2"><YesNoToggle compact value={row.arte_aprovada} onChange={(next) => updateRow(index, "arte_aprovada", next)} /></td>}
                <td className="px-2 py-2"><Input value={row.observacoes || ""} onChange={(event) => updateRow(index, "observacoes", event.target.value)} /></td>
                <td className="px-2 py-2">
                  <div className="flex gap-1">
                    <Button type="button" variant="ghost" size="sm" className="h-8 w-8 p-0" onClick={() => clearRow(index)}>
                      <RotateCcw className="h-3.5 w-3.5" />
                    </Button>
                    <Button type="button" variant="ghost" size="sm" className="h-8 w-8 p-0" onClick={() => removeRow(index)}>
                      <Trash2 className="h-3.5 w-3.5 text-red-500" />
                    </Button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default function KickoffCompositionQuestionnaire({ value, onChange, onSave, saving }) {
  const q = mergeQuestionnaire(value);
  const update = (section, field, nextValue) => {
    onChange({ ...q, [section]: { ...(q[section] || {}), [field]: nextValue } });
  };

  return (
    <div className="space-y-4" data-testid="kickoff-composition-questionnaire">
      <Section title="Bloco 0 - Identificacao e comercial">
        <div className="grid gap-4 md:grid-cols-2">
          <Field label="Cliente" value={q.bloco0.cliente} onChange={(v) => update("bloco0", "cliente", v)} />
          <Field label="Nome do produto" value={q.bloco0.nome_produto} onChange={(v) => update("bloco0", "nome_produto", v)} />
          <ChoiceGroup label="Categoria" value={q.bloco0.categoria} onChange={(v) => update("bloco0", "categoria", v)} options={[
            { value: "perfumaria", label: "Perfumaria" },
            { value: "capilar", label: "Capilar" },
            { value: "skin_care", label: "Skin care" },
            { value: "maquiagem", label: "Maquiagem" },
            { value: "home_care", label: "Home care" },
            { value: "outro", label: "Outro" },
          ]} />
          <ChoiceGroup label="Forma fisica" value={q.bloco0.forma_fisica} onChange={(v) => update("bloco0", "forma_fisica", v)} options={[
            { value: "liquido", label: "Liquido" },
            { value: "creme_gel", label: "Creme / gel" },
            { value: "po", label: "Po" },
            { value: "aerossol", label: "Aerossol" },
            { value: "bastao", label: "Bastao" },
            { value: "outro", label: "Outro" },
          ]} />
          <Field label="Volume / gramatura" value={q.bloco0.volume_gramatura} onChange={(v) => update("bloco0", "volume_gramatura", v)} />
          <Field label="No de SKUs / variacoes" value={q.bloco0.numero_skus_variacoes} onChange={(v) => update("bloco0", "numero_skus_variacoes", v)} />
          <CheckboxGroup label="O que varia entre SKUs" values={q.bloco0.varia_entre_skus} onChange={(v) => update("bloco0", "varia_entre_skus", v)} options={[
            { value: "cor", label: "Cor" },
            { value: "fragrancia", label: "Fragrancia" },
            { value: "versao", label: "Versao" },
            { value: "volume", label: "Volume" },
            { value: "outro", label: "Outro" },
          ]} />
          <Field label="Outro tipo de variacao" value={q.bloco0.varia_entre_skus_outro} onChange={(v) => update("bloco0", "varia_entre_skus_outro", v)} />
          <Field label="Unidades por display" value={q.bloco0.unidades_por_display} onChange={(v) => update("bloco0", "unidades_por_display", v)} />
          <Field label="Displays (ou unidades) por caixa master" value={q.bloco0.displays_ou_unidades_por_caixa_master} onChange={(v) => update("bloco0", "displays_ou_unidades_por_caixa_master", v)} />
          <ChoiceGroup label="Registro / notificacao ANVISA" value={q.bloco0.registro_notificacao_anvisa} onChange={(v) => update("bloco0", "registro_notificacao_anvisa", v)} options={[
            { value: "existe", label: "Existe" },
            { value: "a_providenciar", label: "A providenciar" },
          ]} />
          <Field label="Detentor do registro" value={q.bloco0.detentor_registro} onChange={(v) => update("bloco0", "detentor_registro", v)} />
          <Field label="Responsavel Tecnico (RT)" value={q.bloco0.responsavel_tecnico} onChange={(v) => update("bloco0", "responsavel_tecnico", v)} />
        </div>
        <ChoiceGroup label="Classificacao do projeto (modelo de servico)" value={q.bloco0.modelo_servico} onChange={(v) => update("bloco0", "modelo_servico", v)} options={[
          { value: "industrializacao_pura", label: "Industrializacao pura" },
          { value: "industrializacao_com_desenvolvimento", label: "Industrializacao com desenvolvimento" },
          { value: "full_service_marca_propria", label: "Full service / marca propria" },
        ]} />
      </Section>

      <Section title="Bloco 1 - Formulacao">
        <div className="grid gap-4 md:grid-cols-2">
          <ChoiceGroup label="Formula" value={q.bloco1.formula} onChange={(v) => update("bloco1", "formula", v)} options={[
            { value: "do_cliente", label: "Do cliente" },
            { value: "desenvolvida_kuryos", label: "Desenvolvida pela Kuryos" },
          ]} />
          <CheckboxGroup label="O cliente fornece" values={q.bloco1.cliente_fornece} onChange={(v) => update("bloco1", "cliente_fornece", v)} options={[
            { value: "formula_documento", label: "Formula (documento)" },
            { value: "bulk_pronto", label: "Bulk pronto" },
            { value: "mps", label: "MPs" },
            { value: "nada", label: "Nada (Kuryos compra tudo)" },
          ]} />
          <YesNoToggle label="Tem Cor?" value={q.bloco1.tem_cor} onChange={(v) => update("bloco1", "tem_cor", v)} />
          <YesNoToggle label="Tem Brilho/mica/glitter?" value={q.bloco1.tem_brilho_mica_glitter} onChange={(v) => update("bloco1", "tem_brilho_mica_glitter", v)} />
          <Field label="Qual a viscosidade?" value={q.bloco1.viscosidade} onChange={(v) => update("bloco1", "viscosidade", v)} />
          <Field label="Qual a densidade?" value={q.bloco1.densidade} onChange={(v) => update("bloco1", "densidade", v)} />
          <Field className="md:col-span-2" label="Fragrancia / essencia definida ou aprovada - casa de fragrancia e codigos" value={q.bloco1.fragrancia_essencia} onChange={(v) => update("bloco1", "fragrancia_essencia", v)} />
          <ChoiceGroup label="Compra da fragrancia por" value={q.bloco1.compra_fragrancia_por} onChange={(v) => update("bloco1", "compra_fragrancia_por", v)} options={[{ value: "cliente", label: "Cliente" }, { value: "kuryos", label: "Kuryos" }]} />
          <TextField className="md:col-span-2" label="Observacoes de formulacao" value={q.bloco1.observacoes_formulacao} onChange={(v) => update("bloco1", "observacoes_formulacao", v)} />
        </div>
      </Section>

      <Section title="Bloco 2 - Embalagem primaria e sistema de fechamento">
        <ComponentTable title="Componentes" value={q.bloco2} defaults={BLOCO2_COMPONENTS} onChange={(v) => update("bloco2", "componentes", v.componentes)} />
      </Section>

      <Section title="Bloco 3 - Embalagem secundaria e comunicacao">
        <ComponentTable title="Componentes graficos" value={q.bloco3} defaults={BLOCO3_COMPONENTS} hasArt onChange={(v) => update("bloco3", "componentes", v.componentes)} />
      </Section>

      <Section title="Bloco 4 - Embalagem terciaria e logistica">
        <ComponentTable title="Componentes logisticos" value={q.bloco4} defaults={BLOCO4_COMPONENTS} onChange={(v) => update("bloco4", "componentes", v.componentes)} />
      </Section>

      <Section title="Bloco 5 - Qualidade de recebimento">
        <TextField label="Especificacoes de CQ por componente (texto / anexos)" value={q.bloco5.especificacoes_cq_componentes} onChange={(v) => update("bloco5", "especificacoes_cq_componentes", v)} rows={4} />
        <TextField label="Testes / aprovacoes obrigatorios antes da producao" value={q.bloco5.testes_aprovacoes_obrigatorios} onChange={(v) => update("bloco5", "testes_aprovacoes_obrigatorios", v)} rows={4} />
        <YesNoToggle label="Amostra de referencia fornecida pelo cliente" value={q.bloco5.amostra_referencia_fornecida_cliente} onChange={(v) => update("bloco5", "amostra_referencia_fornecida_cliente", v)} />
      </Section>

      <Section title="Fechamento">
        <div className="grid gap-4 md:grid-cols-2">
          <Field type="date" label="Data prevista de inicio de producao" value={q.fechamento.data_prevista_inicio_producao} onChange={(v) => update("fechamento", "data_prevista_inicio_producao", v)} />
          <Field label="Volume do primeiro lote" value={q.fechamento.volume_primeiro_lote} onChange={(v) => update("fechamento", "volume_primeiro_lote", v)} />
          <Field label="Responsavel Kuryos" value={q.fechamento.responsavel_kuryos} onChange={(v) => update("fechamento", "responsavel_kuryos", v)} />
          <Field label="Responsavel Cliente" value={q.fechamento.responsavel_cliente} onChange={(v) => update("fechamento", "responsavel_cliente", v)} />
          <Field type="date" label="Data do preenchimento" value={q.fechamento.data_preenchimento} onChange={(v) => update("fechamento", "data_preenchimento", v)} />
        </div>
      </Section>

      <div className="sticky bottom-0 z-10 -mx-1 rounded-md border bg-background/95 p-3 backdrop-blur flex justify-end">
        <Button disabled={saving} onClick={onSave}>Salvar questionario</Button>
      </div>
    </div>
  );
}
