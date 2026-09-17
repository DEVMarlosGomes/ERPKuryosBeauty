import { useState, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/contexts/AuthContext";
import api from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent } from "@/components/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "@/components/ui/dialog";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Textarea } from "@/components/ui/textarea";
import { toast } from "sonner";
import { BACKEND_URL } from "@/lib/backend";
import {
  FileText, Plus, Loader2, Download, Search, X, RefreshCw,
  Building2, CheckCircle2, Calendar, PenLine, ShoppingCart
} from "lucide-react";

const CONTRACT_STATUS = {
  gerado: { label: "Gerado — aguardando assinatura", className: "bg-amber-100 text-amber-800 border-amber-200" },
  enviado: { label: "Enviado — aguardando assinatura", className: "bg-blue-100 text-blue-700 border-blue-200" },
  assinado: { label: "Assinado", className: "bg-green-100 text-green-700 border-green-200" },
  vigente: { label: "Vigente", className: "bg-emerald-100 text-emerald-700 border-emerald-200" },
};

function ContractStatusBadge({ contrato }) {
  const status = contrato?.status || "gerado";
  const config = CONTRACT_STATUS[status] || { label: status, className: "bg-muted text-muted-foreground border-border" };
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs border ${config.className}`}>
      <CheckCircle2 className="h-3 w-3" />{config.label}
    </span>
  );
}

function formatDate(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("pt-BR");
}

function formatDateTime(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("pt-BR");
}

function GenerateDialog({ open, onClose, onGenerated }) {
  const [kickoffs, setKickoffs] = useState([]);
  const [loading, setLoading] = useState(false);
  const [selectedKickoff, setSelectedKickoff] = useState("");
  const [overrides, setOverrides] = useState({
    inscricao_estadual: "",
    endereco_completo: "",
    representante_nome: "",
    representante_cpf: "",
    representante_rg: "",
    representante_cargo: "",
  });
  const [observacoes, setObservacoes] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open) return;
    setLoading(true);
    api.get("/kickoffs?status=aprovado").then(({ data }) => {
      setKickoffs(Array.isArray(data) ? data : []);
    }).catch(() => toast.error("Erro ao carregar kickoffs aprovados"))
    .finally(() => setLoading(false));
  }, [open]);

  const handleGenerate = async () => {
    if (!selectedKickoff) { toast.error("Selecione um Kickoff"); return; }
    setSaving(true);
    try {
      const payload = {
        kickoff_id: selectedKickoff,
        observacoes,
        contratante: Object.values(overrides).some(v => v.trim()) ? overrides : undefined,
      };
      await api.post("/contratos/gerar", payload);
      toast.success("Contrato CGI gerado com sucesso");
      onGenerated();
      onClose();
      reset();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Erro ao gerar contrato");
    } finally { setSaving(false); }
  };

  const reset = () => {
    setSelectedKickoff(""); setObservacoes("");
    setOverrides({ inscricao_estadual: "", endereco_completo: "", representante_nome: "", representante_cpf: "", representante_rg: "", representante_cargo: "" });
  };

  const selectedData = kickoffs.find(k => k.id === selectedKickoff);

  return (
    <Dialog open={open} onOpenChange={o => { if (!o) { reset(); onClose(); } }}>
      <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <FileText className="h-5 w-5 text-indigo-600" />
            Gerar Contrato CGI
          </DialogTitle>
          <DialogDescription>
            Selecione um Kickoff aprovado. O contrato será gerado com os dados do cliente e do kickoff.
          </DialogDescription>
        </DialogHeader>

        {loading ? (
          <div className="flex justify-center py-8"><Loader2 className="h-6 w-6 animate-spin text-muted-foreground" /></div>
        ) : (
          <div className="space-y-5">
            <div className="space-y-1">
              <Label className="text-xs font-medium">Kickoff (aprovado) <span className="text-red-500">*</span></Label>
              <Select value={selectedKickoff} onValueChange={setSelectedKickoff}>
                <SelectTrigger>
                  <SelectValue placeholder="Selecione o Kickoff..." />
                </SelectTrigger>
                <SelectContent>
                  {kickoffs.length === 0 && <SelectItem value="__none" disabled>Nenhum Kickoff aprovado</SelectItem>}
                  {kickoffs.map(k => (
                    <SelectItem key={k.id} value={k.id}>
                      {k.numero_kickoff} — {k.bloco1?.cliente || k.bloco1?.projeto_vinculado || k.id}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {selectedData && (
                <div className="mt-1 p-2 bg-muted/40 rounded text-xs space-y-0.5">
                  <p><span className="text-muted-foreground">Cliente:</span> {selectedData.bloco1?.cliente || "—"}</p>
                  <p><span className="text-muted-foreground">Aprovado em:</span> {formatDate(selectedData.approved_at)}</p>
                </div>
              )}
            </div>

            <div className="space-y-3">
              <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">Dados do Contratante (opcional)</p>
              <p className="text-xs text-muted-foreground -mt-2">Preencha apenas campos não disponíveis no cadastro do cliente.</p>
              <div className="grid grid-cols-2 gap-3">
                {[
                  { key: "inscricao_estadual", label: "Inscrição Estadual" },
                  { key: "representante_nome", label: "Representante Legal" },
                  { key: "representante_cpf", label: "CPF do Representante" },
                  { key: "representante_rg", label: "RG do Representante" },
                  { key: "representante_cargo", label: "Cargo" },
                ].map(({ key, label }) => (
                  <div key={key} className="space-y-1">
                    <Label className="text-xs">{label}</Label>
                    <Input
                      value={overrides[key]}
                      onChange={e => setOverrides(o => ({ ...o, [key]: e.target.value }))}
                      placeholder={label}
                      className="h-8 text-sm"
                    />
                  </div>
                ))}
                <div className="col-span-2 space-y-1">
                  <Label className="text-xs">Endereço Completo</Label>
                  <Input
                    value={overrides.endereco_completo}
                    onChange={e => setOverrides(o => ({ ...o, endereco_completo: e.target.value }))}
                    placeholder="Rua, nº, CEP, Cidade/UF"
                    className="h-8 text-sm"
                  />
                </div>
              </div>
            </div>

            <div className="space-y-1">
              <Label className="text-xs font-medium">Observações Adicionais</Label>
              <Textarea
                value={observacoes}
                onChange={e => setObservacoes(e.target.value)}
                rows={3}
                placeholder="Cláusulas adicionais, condições especiais..."
              />
            </div>

            <div className="p-3 bg-indigo-50 border border-indigo-100 rounded-lg text-xs text-indigo-700 space-y-1">
              <p className="font-semibold">Fabricante (fixo):</p>
              <p>KURYOS BEAUTY PACKING INDUSTRIAL LTDA · CNPJ 00.767.554/0001-19</p>
              <p>ANVISA 355030801-206-000078-1-1 · Foro: Comarca de São Paulo/SP</p>
            </div>
          </div>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={() => { reset(); onClose(); }}>Cancelar</Button>
          <Button onClick={handleGenerate} disabled={saving || loading || !selectedKickoff} className="gap-1.5">
            {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileText className="h-4 w-4" />}
            Gerar CGI
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function useDownloadContrato(contrato) {
  const [downloading, setDownloading] = useState(false);
  const handleDownload = async (e) => {
    e?.stopPropagation();
    setDownloading(true);
    try {
      const token = localStorage.getItem("token") || sessionStorage.getItem("token");
      const resp = await fetch(`${BACKEND_URL}/api/contratos/${contrato.id}/pdf`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (!resp.ok) throw new Error("Erro ao baixar PDF");
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${contrato.numero_contrato}.pdf`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      toast.error("Erro ao baixar PDF do contrato");
    } finally { setDownloading(false); }
  };
  return { downloading, handleDownload };
}

function ContratoDetailModal({ contrato, onClose, canSign, onSigned }) {
  const navigate = useNavigate();
  const { downloading, handleDownload } = useDownloadContrato(contrato || {});
  const [signing, setSigning] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [completion, setCompletion] = useState(null);
  if (!contrato) return null;
  const c = contrato.contratante || {};
  const f = contrato.fabricante || {};
  const needsSignature = ["gerado", "enviado"].includes(contrato.status || "gerado");
  const canRetrySku = ["assinado", "vigente"].includes(contrato.status) && contrato.pedido_liberado_para_emissao !== true;

  const handleSign = async () => {
    setSigning(true);
    try {
      const { data } = await api.post(`/contratos/${contrato.id}/assinar`, {
        observacoes: needsSignature ? "Assinatura confirmada no módulo de Contratos" : "Reprocessamento de SKU solicitado no módulo de Contratos",
      });
      const codes = (data.skus_gerados || [])
        .map(item => item.sku?.codigo_interno)
        .filter(Boolean);
      if (data.pedido_liberado_para_emissao) {
        setCompletion({ ...data, skuCodes: codes });
      } else {
        const reason = (data.sku_bloqueios || []).join(" | ") || "Não foi possível gerar o SKU.";
        toast.error(`CGI assinado, mas o pedido não foi liberado: ${reason}`);
      }
      onSigned(data);
    } catch (err) {
      toast.error(err.response?.data?.detail || "Erro ao assinar CGI e gerar SKU");
    } finally {
      setSigning(false);
    }
  };

  return (
    <Dialog open={!!contrato} onOpenChange={(v) => { if (!v) onClose(); }}>
      <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <FileText className="h-5 w-5 text-indigo-600" />
            {contrato.numero_contrato}
          </DialogTitle>
          <DialogDescription className="flex items-center gap-2 flex-wrap">
            <ContractStatusBadge contrato={contrato} />
            <span className="text-xs text-muted-foreground">Kickoff: {contrato.numero_kickoff} · v{contrato.kickoff_versao}</span>
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-5">
          {contrato.status === "assinado" && contrato.pedido_liberado_para_emissao && (
            <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-800 dark:border-emerald-900 dark:bg-emerald-950/30 dark:text-emerald-300">
              <p className="font-semibold">CGI assinado e SKU gerado com sucesso.</p>
              <p className="mt-0.5 text-xs">O pedido está liberado para seguir ao PCP.</p>
            </div>
          )}
          <div>
            <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-2">Contratante</p>
            <div className="grid grid-cols-2 gap-2 text-sm">
              {[
                ["Razão Social", c.razao_social],
                ["CNPJ", c.cnpj],
                ["Inscrição Estadual", c.inscricao_estadual],
                ["Endereço", c.endereco_completo],
                ["Representante", c.representante_nome],
                ["CPF", c.representante_cpf],
                ["RG", c.representante_rg],
                ["Cargo", c.representante_cargo],
              ].filter(([, v]) => v).map(([label, value]) => (
                <div key={label} className={label === "Endereço" ? "col-span-2" : ""}>
                  <p className="text-[10px] text-muted-foreground uppercase tracking-wide">{label}</p>
                  <p className="font-medium">{value}</p>
                </div>
              ))}
            </div>
          </div>
          <div>
            <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-2">Fabricante</p>
            <div className="p-3 bg-indigo-50 dark:bg-indigo-950/30 rounded-lg text-xs space-y-0.5">
              <p className="font-semibold">{f.razao_social}</p>
              {f.cnpj && <p>CNPJ: {f.cnpj}</p>}
              {f.endereco && <p>{f.endereco}</p>}
              {f.anvisa && <p>ANVISA: {f.anvisa}</p>}
              {f.foro && <p>Foro: {f.foro}</p>}
            </div>
          </div>
          {contrato.observacoes && (
            <div>
              <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-1">Observações</p>
              <p className="text-sm whitespace-pre-wrap">{contrato.observacoes}</p>
            </div>
          )}
          <div className="flex items-center gap-4 text-xs text-muted-foreground pt-2 border-t border-border">
            <span className="flex items-center gap-1"><Calendar className="h-3 w-3" />Gerado em {formatDateTime(contrato.created_at)}</span>
            {contrato.created_by_name && <span>por {contrato.created_by_name}</span>}
          </div>
        </div>
        <div className="flex justify-end gap-2 pt-2">
          <Button variant="outline" onClick={onClose}>Fechar</Button>
          {canSign && (needsSignature || canRetrySku) && (
            <Button onClick={() => setConfirmOpen(true)} disabled={signing} className="gap-1.5 bg-green-600 hover:bg-green-700">
              {signing ? <Loader2 className="h-4 w-4 animate-spin" /> : <PenLine className="h-4 w-4" />}
              {needsSignature ? "Assinar CGI e gerar SKU" : "Reprocessar SKU"}
            </Button>
          )}
          <Button onClick={handleDownload} disabled={downloading} className="gap-1.5">
            {downloading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
            Baixar PDF
          </Button>
        </div>

        <AlertDialog open={confirmOpen} onOpenChange={setConfirmOpen}>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>{needsSignature ? "Assinar CGI e gerar SKU?" : "Reprocessar geração do SKU?"}</AlertDialogTitle>
              <AlertDialogDescription>
                {needsSignature
                  ? "Ao confirmar, o CGI será marcado como assinado, o SKU será gerado e vinculado ao pedido para liberação ao PCP."
                  : "O sistema tentará gerar e vincular novamente o SKU pendente ao pedido."}
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel disabled={signing}>Cancelar</AlertDialogCancel>
              <AlertDialogAction onClick={handleSign} disabled={signing} className="bg-green-600 hover:bg-green-700">
                {needsSignature ? "Confirmar assinatura" : "Reprocessar SKU"}
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>

        <Dialog open={!!completion} onOpenChange={(open) => { if (!open) setCompletion(null); }}>
          <DialogContent className="max-w-md">
            <DialogHeader>
              <DialogTitle className="flex items-center gap-2 text-emerald-700">
                <CheckCircle2 className="h-6 w-6" />
                CGI assinado e SKU gerado
              </DialogTitle>
              <DialogDescription>
                O SKU foi vinculado ao pedido, que já está liberado para prosseguir ao PCP.
              </DialogDescription>
            </DialogHeader>
            <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-4 dark:border-emerald-900 dark:bg-emerald-950/30">
              <p className="text-xs font-medium uppercase tracking-wide text-emerald-700 dark:text-emerald-400">SKU gerado</p>
              <p className="mt-1 font-mono text-base font-semibold text-emerald-900 dark:text-emerald-200">
                {completion?.skuCodes?.join(", ") || "SKU vinculado"}
              </p>
              {completion?.numero_pedido && <p className="mt-2 text-sm">Pedido: <strong>{completion.numero_pedido}</strong></p>}
            </div>
            <DialogFooter>
              <Button variant="outline" onClick={() => setCompletion(null)}>Permanecer aqui</Button>
              <Button
                className="gap-2 bg-emerald-600 hover:bg-emerald-700"
                disabled={!completion?.pedido_id}
                onClick={() => {
                  const pedidoId = completion?.pedido_id;
                  setCompletion(null);
                  onClose();
                  if (pedidoId) navigate(`/orders/${pedidoId}`);
                }}
              >
                <ShoppingCart className="h-4 w-4" />Prosseguir para pedido
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </DialogContent>
    </Dialog>
  );
}

function ContratoCard({ contrato, onClick }) {
  const { downloading, handleDownload } = useDownloadContrato(contrato);

  return (
    <Card className="hover:shadow-md transition-shadow cursor-pointer" onClick={onClick}>
      <CardContent className="p-4">
        <div className="flex items-start gap-3">
          <div className="flex items-center justify-center h-10 w-10 rounded-lg bg-indigo-50 text-indigo-600 flex-shrink-0">
            <FileText className="h-5 w-5" />
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="font-semibold">{contrato.numero_contrato}</span>
              <ContractStatusBadge contrato={contrato} />
            </div>
            <p className="text-sm text-muted-foreground mt-0.5 truncate">
              Kickoff: {contrato.numero_kickoff} · v{contrato.kickoff_versao}
            </p>
            <div className="flex items-center gap-4 mt-2 text-xs text-muted-foreground">
              <span className="flex items-center gap-1"><Building2 className="h-3 w-3" />{contrato.contratante?.razao_social || "—"}</span>
              <span className="flex items-center gap-1"><Calendar className="h-3 w-3" />{formatDateTime(contrato.created_at)}</span>
            </div>
            {contrato.observacoes && (
              <p className="text-xs text-muted-foreground mt-1 italic">{contrato.observacoes}</p>
            )}
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={handleDownload}
            disabled={downloading}
            className="gap-1.5 flex-shrink-0"
          >
            {downloading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Download className="h-3.5 w-3.5" />}
            PDF
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

export default function ContratosPage() {
  const { user } = useAuth();
  const [contratos, setContratos] = useState([]);
  const [loading, setLoading] = useState(true);
  const [generateOpen, setGenerateOpen] = useState(false);
  const [search, setSearch] = useState("");

  const canGenerate = user && ["admin", "sales_ops", "vendedor", "compras"].includes(user.role);
  const [selectedContrato, setSelectedContrato] = useState(null);

  const fetchContratos = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await api.get("/contratos");
      setContratos(data.contratos || []);
    } catch { toast.error("Erro ao carregar contratos"); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { fetchContratos(); }, [fetchContratos]);

  const filtered = contratos.filter(c =>
    !search ||
    (c.numero_contrato || "").toLowerCase().includes(search.toLowerCase()) ||
    (c.numero_kickoff || "").toLowerCase().includes(search.toLowerCase()) ||
    (c.contratante?.razao_social || "").toLowerCase().includes(search.toLowerCase())
  );

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-6">
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-heading font-semibold flex items-center gap-2">
            <FileText className="h-6 w-6 text-indigo-600" />
            Contratos CGI
          </h1>
          <p className="text-sm text-muted-foreground mt-0.5">Contratos Gerais de Industrialização vinculados a Kickoffs aprovados</p>
        </div>
        {canGenerate && (
          <Button onClick={() => setGenerateOpen(true)} className="gap-1.5">
            <Plus className="h-4 w-4" />
            Gerar CGI
          </Button>
        )}
      </div>

      <div className="flex gap-2 items-center">
        <div className="relative flex-1 max-w-xs">
          <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input className="pl-8 h-9 text-sm" placeholder="Buscar por contrato, kickoff, cliente..." value={search} onChange={e => setSearch(e.target.value)} />
          {search && <button className="absolute right-2.5 top-2.5" onClick={() => setSearch("")}><X className="h-4 w-4 text-muted-foreground" /></button>}
        </div>
        <Button variant="ghost" size="sm" onClick={fetchContratos} className="h-9 w-9 p-0">
          <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
        </Button>
      </div>

      {loading ? (
        <div className="flex justify-center py-12"><Loader2 className="h-6 w-6 animate-spin text-muted-foreground" /></div>
      ) : filtered.length === 0 ? (
        <div className="text-center py-16 border border-dashed rounded-xl bg-muted/10">
          <FileText className="h-10 w-10 text-muted-foreground/30 mx-auto mb-3" />
          <p className="text-muted-foreground">
            {contratos.length === 0 ? "Nenhum contrato gerado ainda." : "Nenhum contrato corresponde ao filtro."}
          </p>
          {canGenerate && contratos.length === 0 && (
            <Button variant="outline" className="mt-4 gap-1.5" onClick={() => setGenerateOpen(true)}>
              <Plus className="h-4 w-4" />Gerar primeiro CGI
            </Button>
          )}
        </div>
      ) : (
        <div className="space-y-3">
          {filtered.map(c => <ContratoCard key={c.id} contrato={c} onClick={() => setSelectedContrato(c)} />)}
          <p className="text-xs text-muted-foreground text-right pt-1">{filtered.length} contrato{filtered.length !== 1 ? "s" : ""}</p>
        </div>
      )}

      <GenerateDialog open={generateOpen} onClose={() => setGenerateOpen(false)} onGenerated={fetchContratos} />
      <ContratoDetailModal
        contrato={selectedContrato}
        canSign={canGenerate}
        onClose={() => setSelectedContrato(null)}
        onSigned={(updated) => {
          setSelectedContrato(updated);
          setContratos(current => current.map(item => item.id === updated.id ? updated : item));
          fetchContratos();
        }}
      />
    </div>
  );
}
