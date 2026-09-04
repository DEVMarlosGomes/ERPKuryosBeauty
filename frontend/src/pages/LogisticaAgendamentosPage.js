import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import api from "@/lib/api";
import { formatApiError } from "@/lib/formatError";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  CalendarClock,
  ClipboardCheck,
  Loader2,
  PackageCheck,
  Plus,
  Search,
  Truck,
} from "lucide-react";

const STATUS_CLASS = {
  agendado: "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300",
  confirmado: "bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300",
  em_recebimento: "bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300",
  concluido: "bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300",
  pendente: "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300",
  preparando: "bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300",
  conferido: "bg-violet-100 text-violet-700 dark:bg-violet-900/40 dark:text-violet-300",
  expedido: "bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300",
  entregue: "bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300",
  cancelado: "bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300",
};

const STATUS_OPTIONS = ["agendado", "confirmado", "em_recebimento", "concluido", "cancelado"];

function formatDate(value) {
  if (!value) return "Sem data";
  const date = new Date(`${value}T00:00:00`);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString("pt-BR");
}

function emptyForm() {
  return {
    tipo: "entrega",
    titulo: "",
    fornecedor_nome: "",
    po_numero: "",
    data: new Date().toISOString().slice(0, 10),
    hora_inicio: "",
    hora_fim: "",
    doca: "",
    transportadora: "",
    placa: "",
    motorista: "",
    status: "agendado",
    observacoes: "",
  };
}

export default function LogisticaAgendamentosPage() {
  const navigate = useNavigate();
  const [recebimentos, setRecebimentos] = useState([]);
  const [ordens, setOrdens] = useState([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [query, setQuery] = useState("");
  const [tipoFiltro, setTipoFiltro] = useState("todos");
  const [statusFiltro, setStatusFiltro] = useState("todos");
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState(emptyForm());

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [agendaResp, expedicaoResp] = await Promise.all([
        api.get("/recebimento/agendamentos/calendario"),
        api.get("/expedicao/ordens"),
      ]);
      setRecebimentos(agendaResp.data?.agendamentos || []);
      setOrdens(Array.isArray(expedicaoResp.data) ? expedicaoResp.data : []);
    } catch (error) {
      toast.error(formatApiError(error, "Nao foi possivel carregar agendamentos."));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const agendamentos = useMemo(() => {
    const recebimentoItems = recebimentos.map(item => ({
      ...item,
      origem: "recebimento",
      tipo: item.tipo || "entrega",
      titulo: item.titulo || item.fornecedor_nome || item.po_numero || "Recebimento",
      cliente_fornecedor: item.fornecedor_nome || "Fornecedor nao informado",
      documento: item.po_numero ? `PO ${item.po_numero}` : "Sem PO",
    }));
    const expedicaoItems = ordens
      .filter(ordem => ordem.previsao_entrega || ordem.data_expedicao || ordem.data_entrega)
      .map(ordem => ({
        ...ordem,
        origem: "expedicao",
        tipo: "entrega",
        data: ordem.previsao_entrega || ordem.data_entrega || ordem.data_expedicao,
        titulo: ordem.numero_exp || "Expedicao",
        cliente_fornecedor: ordem.cliente_nome || "Cliente nao informado",
        documento: ordem.order_numero ? `Pedido ${ordem.order_numero}` : "Sem pedido",
        hora_inicio: ordem.hora_inicio || "",
        hora_fim: ordem.hora_fim || "",
      }));
    const normalized = query.trim().toLowerCase();
    return [...recebimentoItems, ...expedicaoItems]
      .filter(item => tipoFiltro === "todos" || item.tipo === tipoFiltro || item.origem === tipoFiltro)
      .filter(item => statusFiltro === "todos" || item.status === statusFiltro)
      .filter(item => {
        if (!normalized) return true;
        return [item.titulo, item.cliente_fornecedor, item.documento, item.transportadora, item.placa, item.motorista]
          .filter(Boolean)
          .some(value => String(value).toLowerCase().includes(normalized));
      })
      .sort((a, b) => `${a.data || ""}${a.hora_inicio || ""}`.localeCompare(`${b.data || ""}${b.hora_inicio || ""}`));
  }, [ordens, query, recebimentos, statusFiltro, tipoFiltro]);

  const porData = useMemo(() => {
    return agendamentos.reduce((acc, item) => {
      const key = item.data || "sem_data";
      acc[key] = acc[key] || [];
      acc[key].push(item);
      return acc;
    }, {});
  }, [agendamentos]);

  const stats = useMemo(() => ({
    total: agendamentos.length,
    recebimento: agendamentos.filter(a => a.origem === "recebimento").length,
    expedicao: agendamentos.filter(a => a.origem === "expedicao").length,
    atrasado: agendamentos.filter(a => a.data && a.data < new Date().toISOString().slice(0, 10) && !["concluido", "entregue", "cancelado"].includes(a.status)).length,
  }), [agendamentos]);

  const setField = (key, value) => setForm(prev => ({ ...prev, [key]: value }));

  const saveAgenda = async () => {
    if (!form.data) {
      toast.error("Informe a data do agendamento.");
      return;
    }
    setSaving(true);
    try {
      await api.post("/recebimento/agendamentos", form);
      toast.success("Agendamento criado.");
      setShowForm(false);
      setForm(emptyForm());
      load();
    } catch (error) {
      toast.error(formatApiError(error, "Nao foi possivel criar o agendamento."));
    } finally {
      setSaving(false);
    }
  };

  const updateStatus = async (item, status) => {
    if (item.origem !== "recebimento") {
      toast.info("Status de expedicao deve ser alterado na ordem de expedicao.");
      navigate("/expedicao");
      return;
    }
    try {
      await api.put(`/recebimento/agendamentos/${item.id}`, { status });
      toast.success("Status atualizado.");
      load();
    } catch (error) {
      toast.error(formatApiError(error, "Nao foi possivel atualizar o status."));
    }
  };

  return (
    <div className="min-h-screen space-y-5 p-4 md:p-6" data-testid="logistica-agendamentos-page">
      <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-semibold tracking-tight">
            <CalendarClock className="h-6 w-6 text-primary" />
            Agendamentos Logisticos
          </h1>
          <p className="text-sm text-muted-foreground">
            Coletas, entregas, docas e calendario operacional integrados ao recebimento e expedicao.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" onClick={() => navigate("/recebimento")}>
            <ClipboardCheck className="mr-2 h-4 w-4" />
            Recebimento
          </Button>
          <Button variant="outline" onClick={() => navigate("/expedicao")}>
            <Truck className="mr-2 h-4 w-4" />
            Expedicao
          </Button>
          <Button onClick={() => setShowForm(true)}>
            <Plus className="mr-2 h-4 w-4" />
            Novo
          </Button>
        </div>
      </div>

      <div className="grid gap-3 md:grid-cols-4">
        <Metric label="Total" value={stats.total} />
        <Metric label="Recebimento" value={stats.recebimento} />
        <Metric label="Expedicao" value={stats.expedicao} />
        <Metric label="Atrasados" value={stats.atrasado} tone={stats.atrasado ? "danger" : "default"} />
      </div>

      <div className="grid gap-2 rounded-md border bg-card p-3 md:grid-cols-[1fr_180px_180px]">
        <div className="flex items-center gap-2 rounded-md border bg-background px-3 py-2">
          <Search className="h-4 w-4 text-muted-foreground" />
          <input
            className="min-w-0 flex-1 bg-transparent text-sm outline-none"
            placeholder="Buscar por PO, cliente, fornecedor, placa, motorista..."
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </div>
        <Select value={tipoFiltro} onValueChange={setTipoFiltro}>
          <SelectTrigger>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="todos">Todos os fluxos</SelectItem>
            <SelectItem value="recebimento">Recebimento</SelectItem>
            <SelectItem value="expedicao">Expedicao</SelectItem>
            <SelectItem value="coleta">Coleta</SelectItem>
            <SelectItem value="entrega">Entrega</SelectItem>
          </SelectContent>
        </Select>
        <Select value={statusFiltro} onValueChange={setStatusFiltro}>
          <SelectTrigger>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="todos">Todos os status</SelectItem>
            {[...STATUS_OPTIONS, "pendente", "preparando", "conferido", "expedido", "entregue"].map(status => (
              <SelectItem key={status} value={status}>{status}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {loading ? (
        <div className="flex h-48 items-center justify-center text-muted-foreground">
          <Loader2 className="mr-2 h-5 w-5 animate-spin" />
          Carregando agendamentos
        </div>
      ) : agendamentos.length === 0 ? (
        <Card>
          <CardContent className="py-10 text-center text-sm text-muted-foreground">
            Nenhum agendamento logistico encontrado.
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-4">
          {Object.entries(porData).map(([data, itens]) => (
            <section key={data} className="space-y-2">
              <div className="flex items-center gap-2 text-sm font-semibold text-muted-foreground">
                <CalendarClock className="h-4 w-4" />
                {data === "sem_data" ? "Sem data" : formatDate(data)}
                <Badge variant="outline">{itens.length}</Badge>
              </div>
              <div className="grid gap-3">
                {itens.map(item => (
                  <Card key={`${item.origem}-${item.id || item.numero_exp}`} className="overflow-hidden">
                    <CardContent className="grid gap-4 p-4 lg:grid-cols-[150px_1fr_220px] lg:items-center">
                      <div>
                        <p className="text-xs font-medium uppercase text-muted-foreground">
                          {item.tipo || item.origem}
                        </p>
                        <p className="font-semibold">{item.hora_inicio || "--:--"}{item.hora_fim ? ` - ${item.hora_fim}` : ""}</p>
                        <p className="text-xs text-muted-foreground">{item.doca || "Doca nao definida"}</p>
                      </div>
                      <div className="min-w-0">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="font-semibold">{item.titulo}</span>
                          <Badge className={STATUS_CLASS[item.status] || STATUS_CLASS.pendente}>
                            {item.status || "pendente"}
                          </Badge>
                          <Badge variant="outline">{item.origem}</Badge>
                        </div>
                        <p className="mt-1 truncate text-sm text-muted-foreground">
                          {item.cliente_fornecedor} - {item.documento}
                        </p>
                        <p className="mt-1 text-xs text-muted-foreground">
                          {item.transportadora || "Transportadora nao definida"}
                          {item.placa ? ` - Placa ${item.placa}` : ""}
                          {item.motorista ? ` - ${item.motorista}` : ""}
                        </p>
                      </div>
                      <div className="flex flex-wrap gap-2 lg:justify-end">
                        {item.origem === "recebimento" ? (
                          <Select value={item.status || "agendado"} onValueChange={value => updateStatus(item, value)}>
                            <SelectTrigger className="w-[180px]">
                              <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                              {STATUS_OPTIONS.map(status => (
                                <SelectItem key={status} value={status}>{status}</SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                        ) : (
                          <Button variant="outline" onClick={() => navigate("/expedicao")}>
                            Ver ordem
                          </Button>
                        )}
                      </div>
                    </CardContent>
                  </Card>
                ))}
              </div>
            </section>
          ))}
        </div>
      )}

      <Dialog open={showForm} onOpenChange={setShowForm}>
        <DialogContent className="max-h-[92vh] max-w-2xl overflow-y-auto">
          <DialogHeader>
            <DialogTitle>Novo Agendamento Logistico</DialogTitle>
          </DialogHeader>
          <div className="grid gap-3 md:grid-cols-2">
            <div>
              <Label>Tipo</Label>
              <Select value={form.tipo} onValueChange={value => setField("tipo", value)}>
                <SelectTrigger className="mt-1">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="entrega">Entrega</SelectItem>
                  <SelectItem value="coleta">Coleta</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label>Status</Label>
              <Select value={form.status} onValueChange={value => setField("status", value)}>
                <SelectTrigger className="mt-1">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {STATUS_OPTIONS.map(status => (
                    <SelectItem key={status} value={status}>{status}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <Field label="Titulo" value={form.titulo} onChange={value => setField("titulo", value)} placeholder="Ex: Entrega fornecedor A" />
            <Field label="Fornecedor" value={form.fornecedor_nome} onChange={value => setField("fornecedor_nome", value)} placeholder="Nome do fornecedor" />
            <Field label="PO" value={form.po_numero} onChange={value => setField("po_numero", value)} placeholder="Numero da PO" />
            <Field label="Data" type="date" value={form.data} onChange={value => setField("data", value)} />
            <Field label="Inicio" type="time" value={form.hora_inicio} onChange={value => setField("hora_inicio", value)} />
            <Field label="Fim" type="time" value={form.hora_fim} onChange={value => setField("hora_fim", value)} />
            <Field label="Doca" value={form.doca} onChange={value => setField("doca", value)} placeholder="Doca 01" />
            <Field label="Transportadora" value={form.transportadora} onChange={value => setField("transportadora", value)} />
            <Field label="Placa" value={form.placa} onChange={value => setField("placa", value)} />
            <Field label="Motorista" value={form.motorista} onChange={value => setField("motorista", value)} />
            <div className="md:col-span-2">
              <Label>Observacoes</Label>
              <Input
                className="mt-1"
                value={form.observacoes}
                onChange={event => setField("observacoes", event.target.value)}
                placeholder="Instrucoes de doca, janela, documentos ou restricoes"
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowForm(false)} disabled={saving}>Cancelar</Button>
            <Button onClick={saveAgenda} disabled={saving}>
              {saving ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <PackageCheck className="mr-2 h-4 w-4" />}
              Salvar
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function Metric({ label, value, tone = "default" }) {
  return (
    <Card>
      <CardContent className="p-4">
        <p className="text-xs font-medium uppercase text-muted-foreground">{label}</p>
        <p className={`mt-1 text-2xl font-semibold ${tone === "danger" ? "text-red-500" : "text-foreground"}`}>
          {value}
        </p>
      </CardContent>
    </Card>
  );
}

function Field({ label, value, onChange, type = "text", placeholder = "" }) {
  return (
    <div>
      <Label>{label}</Label>
      <Input
        className="mt-1"
        type={type}
        value={value}
        onChange={event => onChange(event.target.value)}
        placeholder={placeholder}
      />
    </div>
  );
}
