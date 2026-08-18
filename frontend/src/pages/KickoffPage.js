import { useCallback, useEffect, useMemo, useState, useRef } from "react";
import { useNavigate, useParams } from "react-router-dom";
import api from "@/lib/api";
import { formatApiError } from "@/lib/formatError";
import { useAuth } from "@/contexts/AuthContext";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Card, CardContent } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Separator } from "@/components/ui/separator";
import { CheckCircle2, Clock3, Download, XCircle, FileText, Upload, ExternalLink, Package, Loader2 as Loader2Icon } from "lucide-react";
import { toast } from "sonner";
import { hasRole } from "@/components/RoleGuard";

const STATUS_TONE = {
  em_preenchimento: "secondary",
  aguardando_aprovacao: "default",
  aprovado: "outline",
  em_revisao: "secondary",
  substituida: "destructive",
};

const APPROVAL_ROLES = {
  lider_pd: ["admin", "lider_pd"],
  cq: ["admin", "qa"],
  eng_produto: ["admin", "engenharia_produto"],
  direcao: ["admin"],
};

function safeJsonParse(value, fallback) {
  try {
    return JSON.parse(value);
  } catch {
    return fallback;
  }
}

function formatDate(value) {
  if (!value) return "-";
  return new Date(value).toLocaleString("pt-BR");
}

function normalizeBlock3(kickoff) {
  const data = kickoff?.bloco3 || {};
  return {
    ...data,
    parametros_microbiologicos: JSON.stringify(data.parametros_microbiologicos || {}, null, 2),
    restricoes_claims: JSON.stringify(data.restricoes_claims || [], null, 2),
    criterios_fisicoquimicos: JSON.stringify(data.criterios_fisicoquimicos || [], null, 2),
    criterios_microbiologicos: JSON.stringify(data.criterios_microbiologicos || [], null, 2),
    analises_obrigatorias_por_lote: JSON.stringify(data.analises_obrigatorias_por_lote || [], null, 2),
  };
}

function normalizeBlock4(kickoff) {
  const data = kickoff?.bloco4 || {};
  return {
    ...data,
    rotulo_informacoes_obrigatorias_checklist: JSON.stringify(data.rotulo_informacoes_obrigatorias_checklist || {}, null, 2),
  };
}

const SAMPLE_STATUS_LABELS = {
  solicitada: "Solicitada", em_elaboracao: "Em Elaboração", retrabalho: "Retrabalho",
  enviada: "Enviada ao Cliente", aprovada: "Aprovada", reprovada: "Reprovada",
};
const SAMPLE_STATUS_COLORS = {
  solicitada: "bg-gray-100 text-gray-700", em_elaboracao: "bg-blue-100 text-blue-700",
  retrabalho: "bg-amber-100 text-amber-700", enviada: "bg-purple-100 text-purple-700",
  aprovada: "bg-green-100 text-green-700", reprovada: "bg-red-100 text-red-700",
};

function FileUploadInput({ value, onChange, accept = ".png,.jpg,.jpeg,.svg,.pdf" }) {
  const [uploading, setUploading] = useState(false);
  const inputRef = useRef(null);

  const handleFile = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    try {
      const formData = new FormData();
      formData.append("file", file);
      const { data } = await api.post("/upload", formData, { headers: { "Content-Type": "multipart/form-data" } });
      onChange(data.id);
      toast.success(`"${data.original_filename}" enviado.`);
    } catch {
      toast.error("Erro ao enviar arquivo");
    } finally {
      setUploading(false);
      e.target.value = "";
    }
  };

  const handleView = async () => {
    if (!value) return;
    try {
      const { data } = await api.get(`/files/${value}`, { responseType: "blob" });
      const url = URL.createObjectURL(data);
      window.open(url, "_blank");
    } catch {
      toast.error("Erro ao abrir arquivo");
    }
  };

  return (
    <div className="flex items-center gap-2 flex-wrap">
      <input ref={inputRef} type="file" accept={accept} className="hidden" onChange={handleFile} />
      <Button type="button" variant="outline" size="sm" onClick={() => inputRef.current?.click()} disabled={uploading} className="gap-1.5 h-8">
        {uploading ? <Loader2Icon className="h-3.5 w-3.5 animate-spin" /> : <Upload className="h-3.5 w-3.5" />}
        {value ? "Substituir" : "Enviar arquivo"}
      </Button>
      {value && (
        <>
          <button type="button" onClick={handleView} className="text-xs text-indigo-600 hover:underline flex items-center gap-1">
            <ExternalLink className="h-3 w-3" /> Ver
          </button>
          <span className="text-[10px] text-muted-foreground font-mono truncate max-w-[160px]">{value}</span>
        </>
      )}
    </div>
  );
}

export default function KickoffPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { user } = useAuth();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [decisionLoading, setDecisionLoading] = useState(false);
  const [kickoff, setKickoff] = useState(null);
  const [block2, setBlock2] = useState({});
  const [block3, setBlock3] = useState({});
  const [block4, setBlock4] = useState({});
  const [approvalNotes, setApprovalNotes] = useState("");
  const [approvalReason, setApprovalReason] = useState("");
  const [activeTab, setActiveTab] = useState("bloco1");
  const [projSamples, setProjSamples] = useState([]);

  const loadKickoff = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await api.get(`/kickoff/${id}`);
      setKickoff(data);
      setBlock2(data.bloco2 || {});
      setBlock3(normalizeBlock3(data));
      setBlock4(normalizeBlock4(data));
      if (data.projeto_id) {
        api.get("/crm/samples", { params: { projeto_id: data.projeto_id } })
          .then(r => setProjSamples(Array.isArray(r.data) ? r.data : []))
          .catch(() => {});
      }
    } catch (error) {
      toast.error(formatApiError(error));
      navigate("/kickoffs");
    } finally {
      setLoading(false);
    }
  }, [id, navigate]);

  useEffect(() => {
    loadKickoff();
  }, [loadKickoff]);

  const currentApproval = kickoff?.aprovacao_pendente || null;
  const canApproveCurrent = useMemo(() => {
    if (!currentApproval || !user?.role) return false;
    return (APPROVAL_ROLES[currentApproval.etapa] || []).includes(user.role) || user.role === "admin";
  }, [currentApproval, user]);

  const saveBlock = async (endpoint, payloadBuilder, nextTab) => {
    setSaving(true);
    try {
      const { data } = await api.put(endpoint, payloadBuilder());
      toast.success("Kickoff atualizado.");
      setKickoff(data);
      setBlock2(data.bloco2 || {});
      setBlock3(normalizeBlock3(data));
      setBlock4(normalizeBlock4(data));
      if (nextTab) {
        setActiveTab(nextTab);
      }
    } catch (error) {
      toast.error(formatApiError(error));
    } finally {
      setSaving(false);
    }
  };

  const submitApproval = async (decisao) => {
    if (!currentApproval) return;
    if (decisao === "reprovado" && !approvalReason.trim()) {
      toast.error("Informe a justificativa da reprovacao.");
      return;
    }
    setDecisionLoading(true);
    try {
      await api.post(`/kickoff/${id}/aprovacao`, {
        etapa: currentApproval.etapa,
        decisao,
        justificativa: decisao === "reprovado" ? approvalReason : undefined,
        observacoes: approvalNotes || undefined,
      });
      setApprovalNotes("");
      setApprovalReason("");
      toast.success(decisao === "aprovado" ? "Aprovacao registrada." : "Reprovacao registrada.");
      await loadKickoff();
    } catch (error) {
      toast.error(formatApiError(error));
    } finally {
      setDecisionLoading(false);
    }
  };

  if (loading || !kickoff) {
    return <div className="p-6 text-sm text-muted-foreground">Carregando kickoff...</div>;
  }

  const block1 = kickoff.bloco1 || {};

  return (
    <div className="p-4 sm:p-6 lg:p-8 space-y-6" data-testid="kickoff-page">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <div className="flex items-center gap-2 flex-wrap">
            <h1 className="text-2xl sm:text-3xl font-heading font-semibold tracking-tight">{kickoff.numero_kickoff}</h1>
            <Badge variant={STATUS_TONE[kickoff.status] || "secondary"}>{kickoff.status}</Badge>
            <Badge variant="outline">{kickoff.versao}</Badge>
          </div>
          <p className="text-sm text-muted-foreground mt-1">
            {block1.cliente || "-"} · {block1.projeto_vinculado || "-"}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" onClick={() => navigate("/kickoffs")}>Voltar</Button>
          <Button variant="outline" onClick={() => api.post(`/kickoff/${id}/bom/export`, { formato: "csv" }).then(() => toast.success("Exportacao disparada no navegador.")).catch((error) => toast.error(formatApiError(error)))}>
            <Download className="h-4 w-4 mr-2" />
            Exportar BOM
          </Button>
          {kickoff.status === "aprovado" && hasRole(user, ["admin", "sales_ops", "vendedor", "compras"]) && (
            <Button onClick={() => navigate("/contratos")} className="gap-1.5 bg-indigo-600 hover:bg-indigo-700 text-white">
              <FileText className="h-4 w-4" />
              Gerar Contrato
            </Button>
          )}
        </div>
      </div>

      <Card>
        <CardContent className="p-5 space-y-3">
          <div className="flex items-center justify-between gap-3 flex-wrap">
            <div>
              <p className="text-sm font-medium">Progresso operacional</p>
              <p className="text-xs text-muted-foreground">Blocos 1-4 antes da aprovacao sequencial.</p>
            </div>
            <p className="text-sm font-medium">{kickoff.progress?.percentual || 0}%</p>
          </div>
          <Progress value={kickoff.progress?.percentual || 0} />
        </CardContent>
      </Card>

      <Tabs value={activeTab} onValueChange={setActiveTab} className="space-y-4">
        <TabsList className="grid w-full grid-cols-5">
          <TabsTrigger value="bloco1">Bloco 1</TabsTrigger>
          <TabsTrigger value="bloco2">Bloco 2</TabsTrigger>
          <TabsTrigger value="bloco3">Bloco 3</TabsTrigger>
          <TabsTrigger value="bloco4">Bloco 4</TabsTrigger>
          <TabsTrigger value="aprovacao">Aprovacao</TabsTrigger>
        </TabsList>

        <TabsContent value="bloco1">
          <div className="space-y-4">
            <Card><CardContent className="p-5 grid gap-4 md:grid-cols-2">
              {[
                ["Numero", block1.numero_kickoff],
                ["Data abertura", formatDate(block1.data_abertura)],
                ["Cliente", block1.cliente],
                ["CNPJ", block1.cnpj],
                ["Projeto", block1.projeto_vinculado],
                ["Formula vinculada", block1.formula_vinculada],
                ["Formulador responsavel", block1.formulador_responsavel],
                ["Responsavel comercial", block1.responsavel_comercial],
                ["Pre-briefing origem", block1.pre_briefing_origem],
                ["Feedback cliente", block1.feedback_cliente],
              ].map(([label, value]) => (
                <div key={label} className={label === "Pre-briefing origem" || label === "Feedback cliente" ? "md:col-span-2" : ""}>
                  <p className="text-[11px] uppercase tracking-wide text-muted-foreground">{label}</p>
                  <p className="mt-1 text-sm whitespace-pre-wrap">{value || "-"}</p>
                </div>
              ))}
            </CardContent></Card>

            {projSamples.length > 0 && (
              <Card>
                <CardContent className="p-5">
                  <p className="text-sm font-semibold mb-3 flex items-center gap-2">
                    <Package className="h-4 w-4 text-primary" />
                    Amostras do Projeto ({projSamples.length})
                  </p>
                  <div className="overflow-x-auto">
                    <table className="w-full text-xs">
                      <thead>
                        <tr className="border-b text-left text-muted-foreground">
                          <th className="py-2 pr-3">Amostra</th>
                          <th className="py-2 pr-3">Produto</th>
                          <th className="py-2 pr-3">Variação</th>
                          <th className="py-2 pr-3">Status</th>
                          <th className="py-2">SKU</th>
                        </tr>
                      </thead>
                      <tbody>
                        {projSamples.flatMap(s =>
                          (s.variacoes || []).length > 0
                            ? s.variacoes.map(v => ({ s, v }))
                            : [{ s, v: null }]
                        ).map(({ s, v }, idx) => (
                          <tr key={`${s.id}-${v?.id || idx}`} className="border-b last:border-b-0">
                            <td className="py-2 pr-3 font-mono font-semibold text-primary">{s.numero_amostra || s.id?.slice(-6)}</td>
                            <td className="py-2 pr-3">{s.nome_produto || s.nome_amostra || "—"}</td>
                            <td className="py-2 pr-3">{v?.codigo || "—"}</td>
                            <td className="py-2 pr-3">
                              {v ? (
                                <span className={`px-2 py-0.5 rounded-full font-medium ${SAMPLE_STATUS_COLORS[v.status] || "bg-muted text-muted-foreground"}`}>
                                  {SAMPLE_STATUS_LABELS[v.status] || v.status || "—"}
                                </span>
                              ) : (
                                <span className="text-muted-foreground">—</span>
                              )}
                            </td>
                            <td className="py-2">
                              {v?.sku_id ? (
                                <span className="px-2 py-0.5 rounded bg-emerald-100 text-emerald-700 font-mono font-semibold">{v.sku_codigo || v.sku_id}</span>
                              ) : "—"}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </CardContent>
              </Card>
            )}
          </div>
        </TabsContent>

        <TabsContent value="bloco2">
          <Card><CardContent className="p-5 space-y-4">
            <div className="grid gap-4 md:grid-cols-2">
              <div><Label>Volume primeiro pedido</Label><Input value={block2.volume_primeiro_pedido || ""} onChange={(e) => setBlock2((prev) => ({ ...prev, volume_primeiro_pedido: Number(e.target.value) || "" }))} /></div>
              <div><Label>Volume estimado mes</Label><Input value={block2.volume_estimado_mes || ""} onChange={(e) => setBlock2((prev) => ({ ...prev, volume_estimado_mes: Number(e.target.value) || "" }))} /></div>
              <div><Label>Unidade venda</Label><Input value={block2.unidade_venda || ""} onChange={(e) => setBlock2((prev) => ({ ...prev, unidade_venda: e.target.value }))} /></div>
              <div><Label>Quantidade por caixa</Label><Input value={block2.quantidade_por_caixa || ""} onChange={(e) => setBlock2((prev) => ({ ...prev, quantidade_por_caixa: Number(e.target.value) || "" }))} /></div>
              <div><Label>Entrega contratada</Label><Input type="date" value={block2.data_entrega_contratada || ""} onChange={(e) => setBlock2((prev) => ({ ...prev, data_entrega_contratada: e.target.value }))} /></div>
              <div><Label>Lead time producao (dias)</Label><Input value={block2.lead_time_producao_dias_uteis || ""} onChange={(e) => setBlock2((prev) => ({ ...prev, lead_time_producao_dias_uteis: Number(e.target.value) || "" }))} /></div>
              <div><Label>Prazo validade (meses)</Label><Input value={block2.prazo_validade_produto_meses || ""} onChange={(e) => setBlock2((prev) => ({ ...prev, prazo_validade_produto_meses: Number(e.target.value) || "" }))} /></div>
              <div><Label>Preco venda cliente (R$/un)</Label><Input value={block2.preco_venda_cliente_rs_un || ""} onChange={(e) => setBlock2((prev) => ({ ...prev, preco_venda_cliente_rs_un: Number(e.target.value) || "" }))} /></div>
              <div><Label>Condicao pagamento</Label><Input value={block2.condicao_pagamento || ""} onChange={(e) => setBlock2((prev) => ({ ...prev, condicao_pagamento: e.target.value }))} /></div>
              <div><Label>Incoterm</Label><Input value={block2.incoterm || ""} onChange={(e) => setBlock2((prev) => ({ ...prev, incoterm: e.target.value }))} /></div>
              <div className="md:col-span-2"><Label>Endereco entrega</Label><Input value={block2.endereco_entrega || ""} onChange={(e) => setBlock2((prev) => ({ ...prev, endereco_entrega: e.target.value }))} /></div>
              <div><Label>CFOP</Label><Input value={block2.nota_fiscal_cfop || ""} onChange={(e) => setBlock2((prev) => ({ ...prev, nota_fiscal_cfop: e.target.value }))} /></div>
              <div><Label>Data contrato assinado</Label><Input type="date" value={block2.contrato_assinado_data || ""} onChange={(e) => setBlock2((prev) => ({ ...prev, contrato_assinado_data: e.target.value }))} /></div>
              <div><Label>Numero pedido cliente</Label><Input value={block2.numero_pedido_cliente || ""} onChange={(e) => setBlock2((prev) => ({ ...prev, numero_pedido_cliente: e.target.value }))} /></div>
              <div className="space-y-1.5">
                <Label>Contrato assinado (PDF)</Label>
                <FileUploadInput accept=".pdf,.png,.jpg,.jpeg" value={block2.contrato_assinado_file_id || ""} onChange={(fid) => setBlock2((prev) => ({ ...prev, contrato_assinado_file_id: fid }))} />
              </div>
              <div className="md:col-span-2"><Label>Observacoes comerciais</Label><Textarea value={block2.observacoes_comerciais || ""} onChange={(e) => setBlock2((prev) => ({ ...prev, observacoes_comerciais: e.target.value }))} /></div>
            </div>
            <Button disabled={saving} onClick={() => saveBlock(`/kickoff/${id}/bloco2`, () => block2, "bloco3")}>Salvar Bloco 2</Button>
          </CardContent></Card>
        </TabsContent>

        <TabsContent value="bloco3">
          <Card><CardContent className="p-5 space-y-4">
            <div className="grid gap-4 md:grid-cols-2">
              <div><Label>Nome tecnico produto</Label><Input value={block3.nome_tecnico_produto || ""} onChange={(e) => setBlock3((prev) => ({ ...prev, nome_tecnico_produto: e.target.value }))} /></div>
              <div><Label>Nome comercial cliente</Label><Input value={block3.nome_comercial_cliente || ""} onChange={(e) => setBlock3((prev) => ({ ...prev, nome_comercial_cliente: e.target.value }))} /></div>
              <div><Label>Categoria ANVISA</Label><Input value={block3.categoria_anvisa || ""} onChange={(e) => setBlock3((prev) => ({ ...prev, categoria_anvisa: e.target.value }))} /></div>
              <div><Label>Tipo produto</Label><Input value={block3.tipo_produto || ""} onChange={(e) => setBlock3((prev) => ({ ...prev, tipo_produto: e.target.value }))} /></div>
              <div><Label>Forma apresentacao</Label><Input value={block3.forma_apresentacao || ""} onChange={(e) => setBlock3((prev) => ({ ...prev, forma_apresentacao: e.target.value }))} /></div>
              <div><Label>Volume/Peso liquido</Label><Input value={block3.volume_peso_liquido_valor || ""} onChange={(e) => setBlock3((prev) => ({ ...prev, volume_peso_liquido_valor: Number(e.target.value) || "" }))} /></div>
              <div><Label>Unidade</Label><Input value={block3.volume_peso_liquido_unidade || ""} onChange={(e) => setBlock3((prev) => ({ ...prev, volume_peso_liquido_unidade: e.target.value }))} /></div>
              <div><Label>Odor</Label><Input value={block3.odor || ""} onChange={(e) => setBlock3((prev) => ({ ...prev, odor: e.target.value }))} /></div>
              <div><Label>Aspecto visual</Label><Input value={block3.aspecto_visual || ""} onChange={(e) => setBlock3((prev) => ({ ...prev, aspecto_visual: e.target.value }))} /></div>
              <div><Label>pH minimo</Label><Input value={block3.ph_minimo || ""} onChange={(e) => setBlock3((prev) => ({ ...prev, ph_minimo: Number(e.target.value) || "" }))} /></div>
              <div><Label>pH maximo</Label><Input value={block3.ph_maximo || ""} onChange={(e) => setBlock3((prev) => ({ ...prev, ph_maximo: Number(e.target.value) || "" }))} /></div>
              <div><Label>Estabilidade minima (meses)</Label><Input value={block3.estabilidade_minima_comprovada_meses || ""} onChange={(e) => setBlock3((prev) => ({ ...prev, estabilidade_minima_comprovada_meses: Number(e.target.value) || "" }))} /></div>
              <div><Label>Responsavel liberacao lote</Label><Input value={block3.responsavel_liberacao_lote || ""} onChange={(e) => setBlock3((prev) => ({ ...prev, responsavel_liberacao_lote: e.target.value }))} /></div>
              <div className="space-y-1.5">
                <Label>Foto da amostra aprovada</Label>
                <FileUploadInput value={block3.foto_amostra_aprovada_file_id || ""} onChange={(fid) => setBlock3((prev) => ({ ...prev, foto_amostra_aprovada_file_id: fid }))} />
              </div>
              <div className="space-y-1.5">
                <Label>Registro ANVISA (arquivo)</Label>
                <FileUploadInput value={block3.registro_anvisa_file_id || ""} onChange={(fid) => setBlock3((prev) => ({ ...prev, registro_anvisa_file_id: fid }))} />
              </div>
              <div><Label>Registro ANVISA numero</Label><Input value={block3.registro_anvisa_numero || ""} onChange={(e) => setBlock3((prev) => ({ ...prev, registro_anvisa_numero: e.target.value }))} /></div>
              <div className="md:col-span-2"><Label>Plano amostragem</Label><Textarea value={block3.plano_amostragem || ""} onChange={(e) => setBlock3((prev) => ({ ...prev, plano_amostragem: e.target.value }))} /></div>
              <div className="md:col-span-2"><Label>Parametros microbiologicos (JSON)</Label><Textarea value={block3.parametros_microbiologicos || "{}"} onChange={(e) => setBlock3((prev) => ({ ...prev, parametros_microbiologicos: e.target.value }))} rows={5} /></div>
              <div className="md:col-span-2"><Label>Restricoes / claims (JSON array)</Label><Textarea value={block3.restricoes_claims || "[]"} onChange={(e) => setBlock3((prev) => ({ ...prev, restricoes_claims: e.target.value }))} rows={4} /></div>
              <div className="md:col-span-2"><Label>Criterios fisicoquimicos (JSON array)</Label><Textarea value={block3.criterios_fisicoquimicos || "[]"} onChange={(e) => setBlock3((prev) => ({ ...prev, criterios_fisicoquimicos: e.target.value }))} rows={6} /></div>
              <div className="md:col-span-2"><Label>Criterios microbiologicos (JSON array)</Label><Textarea value={block3.criterios_microbiologicos || "[]"} onChange={(e) => setBlock3((prev) => ({ ...prev, criterios_microbiologicos: e.target.value }))} rows={6} /></div>
              <div className="md:col-span-2"><Label>Analises obrigatorias por lote (JSON array)</Label><Textarea value={block3.analises_obrigatorias_por_lote || "[]"} onChange={(e) => setBlock3((prev) => ({ ...prev, analises_obrigatorias_por_lote: e.target.value }))} rows={4} /></div>
            </div>
            <Button
              disabled={saving}
              onClick={() => saveBlock(`/kickoff/${id}/bloco3`, () => ({
                ...block3,
                parametros_microbiologicos: safeJsonParse(block3.parametros_microbiologicos || "{}", {}),
                restricoes_claims: safeJsonParse(block3.restricoes_claims || "[]", []),
                criterios_fisicoquimicos: safeJsonParse(block3.criterios_fisicoquimicos || "[]", []),
                criterios_microbiologicos: safeJsonParse(block3.criterios_microbiologicos || "[]", []),
                analises_obrigatorias_por_lote: safeJsonParse(block3.analises_obrigatorias_por_lote || "[]", []),
              }), "bloco4")}
            >
              Salvar Bloco 3
            </Button>
          </CardContent></Card>
        </TabsContent>

        <TabsContent value="bloco4">
          <div className="space-y-4">
            <Card><CardContent className="p-5 space-y-4">
              <div className="grid gap-4 md:grid-cols-2">
                <div><Label>Embalagem primaria tipo</Label><Input value={block4.embalagem_primaria_tipo || ""} onChange={(e) => setBlock4((prev) => ({ ...prev, embalagem_primaria_tipo: e.target.value }))} /></div>
                <div><Label>Material</Label><Input value={block4.embalagem_primaria_material || ""} onChange={(e) => setBlock4((prev) => ({ ...prev, embalagem_primaria_material: e.target.value }))} /></div>
                <div><Label>Volume nominal</Label><Input value={block4.embalagem_primaria_volume_nominal || ""} onChange={(e) => setBlock4((prev) => ({ ...prev, embalagem_primaria_volume_nominal: Number(e.target.value) || "" }))} /></div>
                <div><Label>Fornecedor primaria</Label><Input value={block4.embalagem_primaria_fornecedor_id || ""} onChange={(e) => setBlock4((prev) => ({ ...prev, embalagem_primaria_fornecedor_id: e.target.value }))} /></div>
                <div><Label>Codigo primaria</Label><Input value={block4.embalagem_primaria_codigo_interno || ""} onChange={(e) => setBlock4((prev) => ({ ...prev, embalagem_primaria_codigo_interno: e.target.value }))} /></div>
                <div><Label>Cor primaria</Label><Input value={block4.embalagem_primaria_cor || ""} onChange={(e) => setBlock4((prev) => ({ ...prev, embalagem_primaria_cor: e.target.value }))} /></div>
                <div className="space-y-1.5">
                  <Label>Laudo embalagem primaria</Label>
                  <FileUploadInput value={block4.embalagem_primaria_laudo_file_id || ""} onChange={(fid) => setBlock4((prev) => ({ ...prev, embalagem_primaria_laudo_file_id: fid }))} />
                </div>
                <div><Label>Fechamento tipo</Label><Input value={block4.fechamento_tipo || ""} onChange={(e) => setBlock4((prev) => ({ ...prev, fechamento_tipo: e.target.value }))} /></div>
                <div><Label>Fornecedor fechamento</Label><Input value={block4.fechamento_fornecedor_id || ""} onChange={(e) => setBlock4((prev) => ({ ...prev, fechamento_fornecedor_id: e.target.value }))} /></div>
                <div><Label>Embalagem secundaria tipo</Label><Input value={block4.embalagem_secundaria_tipo || ""} onChange={(e) => setBlock4((prev) => ({ ...prev, embalagem_secundaria_tipo: e.target.value }))} /></div>
                <div><Label>Fornecedor secundaria</Label><Input value={block4.embalagem_secundaria_fornecedor_id || ""} onChange={(e) => setBlock4((prev) => ({ ...prev, embalagem_secundaria_fornecedor_id: e.target.value }))} /></div>
                <div className="space-y-1.5">
                  <Label>Arte embalagem secundaria</Label>
                  <FileUploadInput value={block4.embalagem_secundaria_arte_file_id || ""} onChange={(fid) => setBlock4((prev) => ({ ...prev, embalagem_secundaria_arte_file_id: fid }))} />
                </div>
                <div><Label>Caixa master tipo</Label><Input value={block4.caixa_master_tipo || ""} onChange={(e) => setBlock4((prev) => ({ ...prev, caixa_master_tipo: e.target.value }))} /></div>
                <div><Label>Caixa master unidades</Label><Input value={block4.caixa_master_unidades || ""} onChange={(e) => setBlock4((prev) => ({ ...prev, caixa_master_unidades: Number(e.target.value) || "" }))} /></div>
                <div><Label>Tipo rotulagem</Label><Input value={block4.tipo_rotulagem || ""} onChange={(e) => setBlock4((prev) => ({ ...prev, tipo_rotulagem: e.target.value }))} /></div>
                <div><Label>Fornecedor rotulo</Label><Input value={block4.rotulo_fornecedor_id || ""} onChange={(e) => setBlock4((prev) => ({ ...prev, rotulo_fornecedor_id: e.target.value }))} /></div>
                <div className="space-y-1.5">
                  <Label>Arte do rotulo</Label>
                  <FileUploadInput value={block4.rotulo_arte_file_id || ""} onChange={(fid) => setBlock4((prev) => ({ ...prev, rotulo_arte_file_id: fid }))} />
                </div>
                <div className="md:col-span-2"><Label>Checklist obrigatorio do rotulo (JSON)</Label><Textarea value={block4.rotulo_informacoes_obrigatorias_checklist || "{}"} onChange={(e) => setBlock4((prev) => ({ ...prev, rotulo_informacoes_obrigatorias_checklist: e.target.value }))} rows={4} /></div>
              </div>
              <Button
                disabled={saving}
                onClick={() => saveBlock(`/kickoff/${id}/bloco4`, () => ({
                  ...block4,
                  rotulo_informacoes_obrigatorias_checklist: safeJsonParse(block4.rotulo_informacoes_obrigatorias_checklist || "{}", {}),
                }), "aprovacao")}
              >
                Salvar Bloco 4
              </Button>
            </CardContent></Card>

            <Card>
              <CardContent className="p-5">
                <div className="flex items-center justify-between gap-3 mb-4">
                  <div>
                    <h3 className="font-medium">BOM consolidado</h3>
                    <p className="text-sm text-muted-foreground">Status de homologacao calculado automaticamente.</p>
                  </div>
                  <Button variant="outline" onClick={loadKickoff}>Atualizar BOM</Button>
                </div>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b text-left">
                        <th className="py-2 pr-3">Codigo</th>
                        <th className="py-2 pr-3">Descricao</th>
                        <th className="py-2 pr-3">Tipo</th>
                        <th className="py-2 pr-3">Fornecedor</th>
                        <th className="py-2 pr-3">Qtd pedido</th>
                        <th className="py-2">Status</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(kickoff.bom || []).map((line) => (
                        <tr key={line.id} className="border-b last:border-b-0">
                          <td className="py-2 pr-3">{line.codigo_interno}</td>
                          <td className="py-2 pr-3">{line.descricao}</td>
                          <td className="py-2 pr-3">{line.tipo}</td>
                          <td className="py-2 pr-3">{line?.fornecedor_principal?.nome || "-"}</td>
                          <td className="py-2 pr-3">{line.quantidade_total_pedido}</td>
                          <td className="py-2">
                            <Badge variant={line.status_homologacao === "homologado" ? "outline" : "secondary"}>
                              {line.status_homologacao}
                            </Badge>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </CardContent>
            </Card>
          </div>
        </TabsContent>

        <TabsContent value="aprovacao">
          <div className="grid gap-4 lg:grid-cols-[1.2fr,0.8fr]">
            <Card>
              <CardContent className="p-5 space-y-4">
                <h3 className="font-medium">Timeline de aprovacao</h3>
                {(kickoff.aprovacoes || []).map((step) => (
                  <div key={step.etapa} className="flex items-start gap-3">
                    <div className="mt-0.5">
                      {step.status === "concluida" ? <CheckCircle2 className="h-5 w-5 text-emerald-600" /> : step.status === "reprovada" ? <XCircle className="h-5 w-5 text-rose-600" /> : <Clock3 className="h-5 w-5 text-amber-600" />}
                    </div>
                    <div className="min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <p className="font-medium">{step.label}</p>
                        <Badge variant={step.status === "concluida" ? "outline" : "secondary"}>{step.status}</Badge>
                      </div>
                      <p className="text-sm text-muted-foreground mt-1">
                        {step.decisao ? `${step.decisao} por ${step.decidido_por_nome || "-"} em ${formatDate(step.decidido_em)}` : "Aguardando decisao"}
                      </p>
                      {(step.justificativa || step.observacoes) && (
                        <p className="text-sm mt-1 whitespace-pre-wrap">{step.justificativa || step.observacoes}</p>
                      )}
                    </div>
                  </div>
                ))}
              </CardContent>
            </Card>

            <Card>
              <CardContent className="p-5 space-y-4">
                <h3 className="font-medium">Acao atual</h3>
                {currentApproval ? (
                  <>
                    <div className="space-y-1">
                      <p className="text-sm text-muted-foreground">Etapa liberada</p>
                      <p className="font-medium">{currentApproval.label}</p>
                    </div>
                    {!canApproveCurrent ? (
                      <p className="text-sm text-muted-foreground">Seu perfil nao pode decidir esta etapa.</p>
                    ) : (
                      <>
                        <div>
                          <Label>Observacoes</Label>
                          <Textarea value={approvalNotes} onChange={(e) => setApprovalNotes(e.target.value)} />
                        </div>
                        <div>
                          <Label>Justificativa de reprovacao</Label>
                          <Textarea value={approvalReason} onChange={(e) => setApprovalReason(e.target.value)} />
                        </div>
                        <div className="flex items-center gap-2">
                          <Button disabled={decisionLoading} onClick={() => submitApproval("aprovado")}>Aprovar</Button>
                          <Button variant="destructive" disabled={decisionLoading} onClick={() => submitApproval("reprovado")}>Reprovar</Button>
                        </div>
                      </>
                    )}
                  </>
                ) : (
                  <p className="text-sm text-muted-foreground">Fluxo concluido.</p>
                )}
                <Separator />
                <div className="text-sm text-muted-foreground space-y-1">
                  <p>Data abertura: {formatDate(kickoff.data_abertura)}</p>
                  <p>Data aprovacao: {formatDate(kickoff.approved_at)}</p>
                </div>
              </CardContent>
            </Card>
          </div>
        </TabsContent>
      </Tabs>
    </div>
  );
}
