import { useCallback, useEffect, useState } from "react";
import api from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import { CheckCircle2, Eye, RefreshCw, Rocket, XCircle } from "lucide-react";
import { toast } from "sonner";
import LegacyStructuredFields from "@/components/legacy/LegacyStructuredFields";

const typeLabels = { supplier: "Fornecedor", material: "Material", sku: "SKU" };

function Stat({ label, value }) {
  return <Card><CardContent className="p-4"><p className="text-xs uppercase text-muted-foreground">{label}</p><p className="mt-1 text-2xl font-semibold">{value || 0}</p></CardContent></Card>;
}

export default function LegacyMasterDataReviewPanel({ globalSearch = "" }) {
  const [rows, setRows] = useState([]);
  const [summary, setSummary] = useState({});
  const [recordType, setRecordType] = useState("todos");
  const [loading, setLoading] = useState(false);
  const [detail, setDetail] = useState(null);
  const [decision, setDecision] = useState(null);
  const [supplierDecision, setSupplierDecision] = useState(null);
  const [suppliers, setSuppliers] = useState([]);
  const [skuDecision, setSkuDecision] = useState(null);
  const [clients, setClients] = useState([]);
  const [skus, setSkus] = useState([]);
  const [promotion, setPromotion] = useState(null);
  const [processing, setProcessing] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const response = await api.get("/cadastros/revisoes-cadastros-bloqueados", {
        params: { record_type: recordType, q: globalSearch || undefined },
      });
      setRows(response.data.registros || []);
      setSummary(response.data.resumo || {});
    } catch (error) {
      toast.error(error.response?.data?.detail || "Erro ao carregar pendências de cadastro.");
    } finally {
      setLoading(false);
    }
  }, [globalSearch, recordType]);

  useEffect(() => {
    const timer = window.setTimeout(load, 250);
    return () => window.clearTimeout(timer);
  }, [load]);

  const openDetail = async (row) => {
    try {
      const response = await api.get(`/cadastros/revisoes-cadastros-bloqueados/${row.id}`);
      setDetail(response.data);
    } catch (error) {
      toast.error(error.response?.data?.detail || "Não foi possível abrir a pendência.");
    }
  };

  const openDecision = (row) => {
    const suggested = ["materiais:MP", "materiais:EP", "materiais:ES", "materiais:RT", "fragrancias"].includes(row.suggested_domain)
      ? row.suggested_domain : "materiais:RT";
    const rawUnit = String(row.legacy_unit || "").toLowerCase();
    const normalizedUnit = ({ lt: "l", litro: "l", unidade: "un" })[rawUnit] || rawUnit;
    const unit = ["kg", "g", "l", "ml", "un", "m"].includes(normalizedUnit) ? normalizedUnit : (suggested.includes("EP") || suggested.includes("ES") || suggested.includes("RT") ? "un" : "kg");
    setDecision({ row, target_domain: suggested, unidade_estoque: unit, unidade_compra: unit, nome_corrigido: row.legacy_name || "", justificativa: "" });
  };

  const submitDecision = async (action) => {
    if (!decision || decision.justificativa.trim().length < 3) {
      toast.error("Informe uma justificativa com pelo menos 3 caracteres.");
      return;
    }
    setProcessing(true);
    try {
      await api.post(`/cadastros/revisoes-cadastros-bloqueados/${decision.row.id}/decisao-material`, {
        decision: action,
        justificativa: decision.justificativa.trim(),
        target_domain: action === "aprovar" ? decision.target_domain : null,
        unidade_estoque: action === "aprovar" ? decision.unidade_estoque : null,
        unidade_compra: action === "aprovar" ? decision.unidade_compra : null,
        nome_corrigido: action === "aprovar" ? decision.nome_corrigido.trim() : null,
      });
      toast.success(action === "aprovar" ? "Classificação aprovada. Material continua bloqueado até a promoção." : "Material reprovado para cadastro.");
      setDecision(null);
      await load();
    } catch (error) {
      toast.error(error.response?.data?.detail || "Não foi possível registrar a decisão.");
    } finally {
      setProcessing(false);
    }
  };

  const promote = async () => {
    if (!promotion) return;
    setProcessing(true);
    try {
      const response = await api.post(`/cadastros/revisoes-cadastros-bloqueados/${promotion.id}/promover-material`);
      toast.success(`Material promovido com o código ${response.data.registro?.codigo_interno || "gerado"}.`);
      setPromotion(null);
      await load();
    } catch (error) {
      toast.error(error.response?.data?.detail || "Não foi possível promover o material.");
    } finally {
      setProcessing(false);
    }
  };

  const openSupplierDecision = async (row) => {
    const mode = row.classification === "conflict" ? "consolidar" : "criar";
    setSupplierDecision({ row, resolution_mode: mode, cnpj_corrigido: /^\d{14}$/.test(row.legacy_code || "") ? row.legacy_code : "", razao_social_corrigida: row.legacy_name || "", target_supplier_id: "", justificativa: "" });
    if (!suppliers.length) {
      try {
        const response = await api.get("/cadastros/fornecedores");
        setSuppliers(response.data.fornecedores || []);
      } catch (error) {
        toast.error(error.response?.data?.detail || "Não foi possível carregar fornecedores para consolidação.");
      }
    }
  };

  const submitSupplierDecision = async (action) => {
    if (!supplierDecision || supplierDecision.justificativa.trim().length < 3) {
      toast.error("Informe uma justificativa com pelo menos 3 caracteres.");
      return;
    }
    setProcessing(true);
    try {
      await api.post(`/cadastros/revisoes-cadastros-bloqueados/${supplierDecision.row.id}/decisao-fornecedor`, {
        decision: action,
        justificativa: supplierDecision.justificativa.trim(),
        resolution_mode: action === "aprovar" ? supplierDecision.resolution_mode : null,
        cnpj_corrigido: action === "aprovar" && supplierDecision.resolution_mode === "criar" ? supplierDecision.cnpj_corrigido : null,
        razao_social_corrigida: action === "aprovar" && supplierDecision.resolution_mode === "criar" ? supplierDecision.razao_social_corrigida : null,
        target_supplier_id: action === "aprovar" && supplierDecision.resolution_mode === "consolidar" ? supplierDecision.target_supplier_id : null,
      });
      toast.success(action === "aprovar" ? "Resolução aprovada. Fornecedor continua bloqueado até confirmar." : "Fornecedor reprovado para cadastro.");
      setSupplierDecision(null);
      await load();
    } catch (error) {
      toast.error(error.response?.data?.detail || "Não foi possível registrar a decisão.");
    } finally {
      setProcessing(false);
    }
  };

  const promoteSupplier = async () => {
    if (!promotion) return;
    setProcessing(true);
    try {
      const response = await api.post(`/cadastros/revisoes-cadastros-bloqueados/${promotion.id}/promover-fornecedor`);
      toast.success(response.data.status === "consolidado" ? "Fornecedor legado consolidado no cadastro selecionado." : `Fornecedor criado com o código ${response.data.registro?.codigo_interno}.`);
      setPromotion(null);
      setSuppliers([]);
      await load();
    } catch (error) {
      toast.error(error.response?.data?.detail || "Não foi possível resolver o fornecedor.");
    } finally {
      setProcessing(false);
    }
  };

  const openSkuDecision = async (row) => {
    setSkuDecision({ row, resolution_mode: "criar", cliente_id: "", codigo_corrigido: row.legacy_code || "", nome_corrigido: row.legacy_name || "", target_sku_id: "", justificativa: "" });
    try {
      const requests = [];
      if (!clients.length) requests.push(api.get("/cadastros/clientes"));
      else requests.push(Promise.resolve(null));
      if (!skus.length) requests.push(api.get("/cadastros/produtos"));
      else requests.push(Promise.resolve(null));
      const [clientResponse, skuResponse] = await Promise.all(requests);
      if (clientResponse) setClients(clientResponse.data.clientes || []);
      if (skuResponse) setSkus(skuResponse.data.produtos || []);
    } catch (error) {
      toast.error(error.response?.data?.detail || "Não foi possível carregar clientes e SKUs para resolução.");
    }
  };

  const submitSkuDecision = async (action) => {
    if (!skuDecision || skuDecision.justificativa.trim().length < 3) {
      toast.error("Informe uma justificativa com pelo menos 3 caracteres.");
      return;
    }
    setProcessing(true);
    try {
      await api.post(`/cadastros/revisoes-cadastros-bloqueados/${skuDecision.row.id}/decisao-sku`, {
        decision: action,
        justificativa: skuDecision.justificativa.trim(),
        resolution_mode: action === "aprovar" ? skuDecision.resolution_mode : null,
        cliente_id: action === "aprovar" && skuDecision.resolution_mode === "criar" ? skuDecision.cliente_id : null,
        codigo_corrigido: action === "aprovar" && skuDecision.resolution_mode === "criar" ? skuDecision.codigo_corrigido : null,
        nome_corrigido: action === "aprovar" && skuDecision.resolution_mode === "criar" ? skuDecision.nome_corrigido : null,
        target_sku_id: action === "aprovar" && skuDecision.resolution_mode === "consolidar" ? skuDecision.target_sku_id : null,
      });
      toast.success(action === "aprovar" ? "Resolução aprovada. SKU continua bloqueado até confirmar." : "SKU reprovado para cadastro.");
      setSkuDecision(null);
      await load();
    } catch (error) {
      toast.error(error.response?.data?.detail || "Não foi possível registrar a decisão do SKU.");
    } finally {
      setProcessing(false);
    }
  };

  const promoteSku = async () => {
    if (!promotion) return;
    setProcessing(true);
    try {
      const response = await api.post(`/cadastros/revisoes-cadastros-bloqueados/${promotion.id}/promover-sku`);
      toast.success(response.data.status === "consolidado" ? "SKU legado consolidado no cadastro selecionado." : `SKU legado criado com o código ${response.data.registro?.codigo_interno}.`);
      setPromotion(null);
      setSkus([]);
      await load();
    } catch (error) {
      toast.error(error.response?.data?.detail || "Não foi possível resolver o SKU.");
    } finally {
      setProcessing(false);
    }
  };

  return (
    <div className="space-y-4">
      <div>
        <h3 className="text-lg font-semibold">Cadastros bloqueados da migração</h3>
        <p className="text-sm text-muted-foreground">Itens que exigem correção humana antes de entrar nos cadastros operacionais.</p>
      </div>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Total pendente" value={summary.total} />
        <Stat label="Fornecedores" value={summary.supplier} />
        <Stat label="Materiais" value={summary.material} />
        <Stat label="SKUs" value={summary.sku} />
      </div>
      <Card>
        <CardHeader className="pb-3">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
            <CardTitle className="flex-1 text-base">Fila de saneamento</CardTitle>
            <Select value={recordType} onValueChange={setRecordType}>
              <SelectTrigger className="w-full sm:w-52"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="todos">Todos os tipos</SelectItem>
                <SelectItem value="supplier">Fornecedores</SelectItem>
                <SelectItem value="material">Materiais</SelectItem>
                <SelectItem value="sku">SKUs</SelectItem>
              </SelectContent>
            </Select>
            <Button variant="outline" onClick={load} disabled={loading} className="gap-2"><RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} /> Atualizar</Button>
          </div>
        </CardHeader>
        <CardContent>
          <div className="overflow-x-auto rounded-md border">
            <Table>
              <TableHeader><TableRow><TableHead>Tipo</TableHead><TableHead>Código</TableHead><TableHead>Nome</TableHead><TableHead>Motivo</TableHead><TableHead>Status</TableHead><TableHead>Ações</TableHead></TableRow></TableHeader>
              <TableBody>
                {rows.map((row) => (
                  <TableRow key={row.id}>
                    <TableCell><Badge variant="outline">{typeLabels[row.record_type] || row.record_type}</Badge></TableCell>
                    <TableCell className="font-mono text-xs">{row.legacy_code || row.source_key}</TableCell>
                    <TableCell>{row.legacy_name || "-"}</TableCell>
                    <TableCell className="max-w-md text-xs text-muted-foreground">{row.reason}</TableCell>
                    <TableCell><Badge variant="outline">{String(["promovido", "consolidado"].includes(row.activation_status) ? row.activation_status : row.review_status || "pendente").replaceAll("_", " ")}</Badge></TableCell>
                    <TableCell><div className="flex gap-1">
                      <Button size="icon" variant="ghost" onClick={() => openDetail(row)} title="Ver origem"><Eye className="h-4 w-4" /></Button>
                      {row.record_type === "material" && row.activation_status !== "promovido" && <Button size="sm" variant="outline" onClick={() => openDecision(row)}>Classificar</Button>}
                      {row.record_type === "material" && row.review_status === "aprovado" && row.activation_status === "bloqueado" && <Button size="sm" onClick={() => setPromotion(row)} className="gap-1"><Rocket className="h-3.5 w-3.5" /> Promover</Button>}
                      {row.record_type === "supplier" && !["promovido", "consolidado"].includes(row.activation_status) && <Button size="sm" variant="outline" onClick={() => openSupplierDecision(row)}>Resolver</Button>}
                      {row.record_type === "supplier" && row.review_status === "aprovado" && row.activation_status === "bloqueado" && <Button size="sm" onClick={() => setPromotion(row)} className="gap-1"><Rocket className="h-3.5 w-3.5" /> Confirmar</Button>}
                      {row.record_type === "sku" && !["promovido", "consolidado"].includes(row.activation_status) && <Button size="sm" variant="outline" onClick={() => openSkuDecision(row)}>Resolver</Button>}
                      {row.record_type === "sku" && row.review_status === "aprovado" && row.activation_status === "bloqueado" && <Button size="sm" onClick={() => setPromotion(row)} className="gap-1"><Rocket className="h-3.5 w-3.5" /> Confirmar</Button>}
                    </div></TableCell>
                  </TableRow>
                ))}
                {!rows.length && <TableRow><TableCell colSpan={6} className="py-8 text-center text-muted-foreground">{loading ? "Carregando..." : "Nenhuma pendência encontrada."}</TableCell></TableRow>}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>
      <Dialog open={Boolean(detail)} onOpenChange={(open) => !open && setDetail(null)}>
        <DialogContent className="max-h-[90vh] max-w-4xl overflow-y-auto">
          <DialogHeader><DialogTitle>Pendência — {detail?.legacy_code || detail?.source_key}</DialogTitle></DialogHeader>
          {detail && <div className="space-y-3 text-sm">
            <p><strong>Motivo:</strong> {detail.reason}</p>
            <p><strong>Decisão:</strong> {String(detail.required_decision || "").replaceAll("_", " ")}</p>
            <p><strong>Status:</strong> {detail.activation_status} / {detail.review_status}</p>
            <LegacyStructuredFields data={detail.source_payload || {}} />
          </div>}
        </DialogContent>
      </Dialog>
      <Dialog open={Boolean(decision)} onOpenChange={(open) => !open && setDecision(null)}>
        <DialogContent className="max-w-2xl">
          <DialogHeader><DialogTitle>Classificar material — {decision?.row.legacy_code}</DialogTitle></DialogHeader>
          {decision && <div className="space-y-4">
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="space-y-1"><Label>Domínio operacional</Label><Select value={decision.target_domain} onValueChange={(value) => setDecision({ ...decision, target_domain: value, ...(value.includes("EP") || value.includes("ES") || value.includes("RT") ? { unidade_estoque: "un", unidade_compra: "un" } : {}) })}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent>
                <SelectItem value="materiais:MP">Matéria-prima (MP)</SelectItem><SelectItem value="materiais:EP">Embalagem primária (EP)</SelectItem><SelectItem value="materiais:ES">Embalagem secundária (ES)</SelectItem><SelectItem value="materiais:RT">Rótulo/etiqueta (RT)</SelectItem><SelectItem value="fragrancias">Fragrância</SelectItem>
              </SelectContent></Select></div>
              <div className="space-y-1"><Label>Nome corrigido</Label><Input value={decision.nome_corrigido} onChange={(event) => setDecision({ ...decision, nome_corrigido: event.target.value })} /></div>
              {[["unidade_estoque", "Unidade de estoque"], ["unidade_compra", "Unidade de compra"]].map(([field, label]) => <div className="space-y-1" key={field}><Label>{label}</Label><Select value={decision[field]} onValueChange={(value) => setDecision({ ...decision, [field]: value })}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent>{["kg", "g", "l", "ml", "un", "m"].map((unit) => <SelectItem key={unit} value={unit}>{unit}</SelectItem>)}</SelectContent></Select></div>)}
            </div>
            <div className="space-y-1"><Label>Justificativa obrigatória</Label><Textarea value={decision.justificativa} onChange={(event) => setDecision({ ...decision, justificativa: event.target.value })} placeholder="Informe a evidência usada para classificar ou reprovar..." /></div>
            <div className="flex justify-end gap-2"><Button variant="destructive" onClick={() => submitDecision("reprovar")} disabled={processing} className="gap-1"><XCircle className="h-4 w-4" /> Reprovar</Button><Button onClick={() => submitDecision("aprovar")} disabled={processing} className="gap-1"><CheckCircle2 className="h-4 w-4" /> Aprovar classificação</Button></div>
          </div>}
        </DialogContent>
      </Dialog>
      <Dialog open={Boolean(promotion)} onOpenChange={(open) => !open && setPromotion(null)}>
        <DialogContent>
          <DialogHeader><DialogTitle>{promotion?.record_type === "supplier" ? "Confirmar resolução do fornecedor" : promotion?.record_type === "sku" ? "Confirmar resolução do SKU legado" : "Promover material aprovado"}</DialogTitle></DialogHeader>
          <p className="text-sm text-muted-foreground">{promotion?.record_type === "supplier" ? "Esta ação criará o fornecedor ou registrará a consolidação conforme a resolução aprovada." : promotion?.record_type === "sku" ? "Esta ação criará o SKU como legado autorizado ou registrará sua consolidação. O fluxo atual de geração por CGI não será alterado." : "Esta ação criará o cadastro operacional na homologação usando a classificação aprovada. Nenhum estoque ou saldo será criado."}</p>
          <div className="flex justify-end gap-2"><Button variant="outline" onClick={() => setPromotion(null)}>Cancelar</Button><Button onClick={promotion?.record_type === "supplier" ? promoteSupplier : promotion?.record_type === "sku" ? promoteSku : promote} disabled={processing} className="gap-1"><Rocket className="h-4 w-4" /> Confirmar</Button></div>
        </DialogContent>
      </Dialog>
      <Dialog open={Boolean(supplierDecision)} onOpenChange={(open) => !open && setSupplierDecision(null)}>
        <DialogContent className="max-w-2xl">
          <DialogHeader><DialogTitle>Resolver fornecedor — {supplierDecision?.row.legacy_name}</DialogTitle></DialogHeader>
          {supplierDecision && <div className="space-y-4">
            <div className="space-y-1"><Label>Tratamento</Label><Select value={supplierDecision.resolution_mode} onValueChange={(value) => setSupplierDecision({ ...supplierDecision, resolution_mode: value })}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="criar">Criar fornecedor com CNPJ corrigido</SelectItem><SelectItem value="consolidar">Consolidar em fornecedor existente</SelectItem></SelectContent></Select></div>
            {supplierDecision.resolution_mode === "criar" ? <div className="grid gap-3 sm:grid-cols-2">
              <div className="space-y-1"><Label>CNPJ corrigido</Label><Input value={supplierDecision.cnpj_corrigido} onChange={(event) => setSupplierDecision({ ...supplierDecision, cnpj_corrigido: event.target.value })} placeholder="Somente números ou formatado" /></div>
              <div className="space-y-1"><Label>Razão social</Label><Input value={supplierDecision.razao_social_corrigida} onChange={(event) => setSupplierDecision({ ...supplierDecision, razao_social_corrigida: event.target.value })} /></div>
            </div> : <div className="space-y-1"><Label>Fornecedor de destino</Label><Select value={supplierDecision.target_supplier_id} onValueChange={(value) => setSupplierDecision({ ...supplierDecision, target_supplier_id: value })}><SelectTrigger><SelectValue placeholder="Selecione o cadastro oficial" /></SelectTrigger><SelectContent>{suppliers.map((supplier) => <SelectItem key={supplier.id} value={supplier.id}>{supplier.codigo_interno} — {supplier.razao_social} — {supplier.cnpj}</SelectItem>)}</SelectContent></Select></div>}
            <div className="space-y-1"><Label>Justificativa obrigatória</Label><Textarea value={supplierDecision.justificativa} onChange={(event) => setSupplierDecision({ ...supplierDecision, justificativa: event.target.value })} placeholder="Informe a evidência do CNPJ ou da consolidação..." /></div>
            <div className="flex justify-end gap-2"><Button variant="destructive" onClick={() => submitSupplierDecision("reprovar")} disabled={processing} className="gap-1"><XCircle className="h-4 w-4" /> Reprovar</Button><Button onClick={() => submitSupplierDecision("aprovar")} disabled={processing} className="gap-1"><CheckCircle2 className="h-4 w-4" /> Aprovar resolução</Button></div>
          </div>}
        </DialogContent>
      </Dialog>
      <Dialog open={Boolean(skuDecision)} onOpenChange={(open) => !open && setSkuDecision(null)}>
        <DialogContent className="max-h-[85vh] max-w-2xl overflow-y-auto">
          <DialogHeader><DialogTitle>Resolver SKU legado — {skuDecision?.row.legacy_name}</DialogTitle></DialogHeader>
          {skuDecision && <div className="space-y-4">
            <div className="space-y-1"><Label>Tratamento</Label><Select value={skuDecision.resolution_mode} onValueChange={(value) => setSkuDecision({ ...skuDecision, resolution_mode: value })}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="criar">Criar como SKU legado autorizado</SelectItem><SelectItem value="consolidar">Consolidar em SKU existente</SelectItem></SelectContent></Select></div>
            {skuDecision.resolution_mode === "criar" ? <div className="grid gap-3 sm:grid-cols-2">
              <div className="space-y-1 sm:col-span-2"><Label>Cliente responsável</Label><Select value={skuDecision.cliente_id} onValueChange={(value) => setSkuDecision({ ...skuDecision, cliente_id: value })}><SelectTrigger><SelectValue placeholder="Selecione o cliente correto" /></SelectTrigger><SelectContent>{clients.map((client) => <SelectItem key={client.id} value={client.id}>{client.nome_empresa} — {client.cli4 || "sem CLI4"}</SelectItem>)}</SelectContent></Select></div>
              <div className="space-y-1"><Label>Código corrigido</Label><Input value={skuDecision.codigo_corrigido} onChange={(event) => setSkuDecision({ ...skuDecision, codigo_corrigido: event.target.value })} /></div>
              <div className="space-y-1"><Label>Nome corrigido</Label><Input value={skuDecision.nome_corrigido} onChange={(event) => setSkuDecision({ ...skuDecision, nome_corrigido: event.target.value })} /></div>
            </div> : <div className="space-y-1"><Label>SKU de destino</Label><Select value={skuDecision.target_sku_id} onValueChange={(value) => setSkuDecision({ ...skuDecision, target_sku_id: value })}><SelectTrigger><SelectValue placeholder="Selecione o SKU oficial" /></SelectTrigger><SelectContent>{skus.map((sku) => <SelectItem key={sku.id} value={sku.id}>{sku.codigo_interno} — {sku.nome_produto} — {sku.cliente_nome}</SelectItem>)}</SelectContent></Select></div>}
            <p className="rounded-md border border-amber-500/30 bg-amber-500/10 p-3 text-xs text-muted-foreground">A criação será marcada como legado autorizado e sem CGI. Isso não libera geração antecipada de SKU nos projetos novos.</p>
            <div className="space-y-1"><Label>Justificativa obrigatória</Label><Textarea value={skuDecision.justificativa} onChange={(event) => setSkuDecision({ ...skuDecision, justificativa: event.target.value })} placeholder="Informe a evidência do cliente, código ou consolidação..." /></div>
            <div className="flex justify-end gap-2"><Button variant="destructive" onClick={() => submitSkuDecision("reprovar")} disabled={processing} className="gap-1"><XCircle className="h-4 w-4" /> Reprovar</Button><Button onClick={() => submitSkuDecision("aprovar")} disabled={processing} className="gap-1"><CheckCircle2 className="h-4 w-4" /> Aprovar resolução</Button></div>
          </div>}
        </DialogContent>
      </Dialog>
    </div>
  );
}
