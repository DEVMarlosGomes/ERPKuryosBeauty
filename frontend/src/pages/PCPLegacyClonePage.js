import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  CalendarDays,
  Check,
  ClipboardList,
  Download,
  FileSpreadsheet,
  PackageCheck,
  Plus,
  Radio,
  RefreshCw,
  Search,
  ShoppingCart,
  Trash2,
} from "lucide-react";
import { toast } from "sonner";

import api from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";

const WEEK_TABS = ["Seg", "Ter", "Qua", "Qui", "Sex"];
const WORK_DAYS = [["seg", "Segunda"], ["ter", "Terca"], ["qua", "Quarta"], ["qui", "Quinta"], ["sex", "Sexta"], ["sab", "Sabado"], ["dom", "Domingo"]];
const CHECK_STEPS = [["sep", "SEP."], ["fab", "FAB."], ["env", "ENV."], ["rot", "ROT."], ["qual", "QUAL."]];
const DEFAULT_POSTS = ["Celofane", "Filme Shrink", "Corte de Pescante", "Remocao de Tampas", "Rotulagem Manual", "Montagem de Cartuchos"];
const DEFAULT_STOP_REASONS = ["Quebra de Maquina", "Setup / Troca de Lote", "Falta de Material", "Ajuste Tecnico", "Limpeza", "Falta de Operador", "Outros"];
const DEFAULT_CLOSE_REASONS = ["Hora extra", "Atraso no encerramento", "Problema tecnico", "Outros"];
const MATRIX_COLUMNS = [
  ["ART", ["arte", "art"]],
  ["ANV", ["anvisa", "anv"]],
  ["ROT", ["rotulo", "rot"]],
  ["FRA", ["frasco", "fra"]],
  ["TAM", ["tampa", "tam"]],
  ["CAR", ["cartucho", "cart"]],
  ["VAL", ["valvula", "val"]],
  ["CEL", ["celofane", "cel"]],
  ["DIS", ["display", "dis"]],
  ["CAI", ["caixa", "cai"]],
  ["ESS", ["essencia", "ess"]],
  ["MP", ["materia", "mp"]],
  ["OK", ["ok"]],
];

function fmt(value) {
  return Number(value || 0).toLocaleString("pt-BR");
}

function ymd(date) {
  return date.toISOString().slice(0, 10);
}

function parseDate(value) {
  const [year, month, day] = String(value || ymd(new Date())).slice(0, 10).split("-").map(Number);
  return new Date(year, month - 1, day);
}

function addDays(value, days) {
  const date = parseDate(value);
  date.setDate(date.getDate() + days);
  return ymd(date);
}

function startOfWeek(value) {
  const date = parseDate(value);
  const day = date.getDay();
  date.setDate(date.getDate() - (day === 0 ? 6 : day - 1));
  return ymd(date);
}

function dateBR(value) {
  if (!value) return "-";
  return parseDate(value).toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" });
}

function isoWeek(value) {
  const date = parseDate(value);
  date.setDate(date.getDate() + 3 - ((date.getDay() + 6) % 7));
  const week1 = new Date(date.getFullYear(), 0, 4);
  return 1 + Math.round(((date - week1) / 86400000 - 3 + ((week1.getDay() + 6) % 7)) / 7);
}

function norm(value) {
  return String(value || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
}

function csvDownload(filename, rows) {
  const csv = rows.map((row) => row.map((cell) => `"${String(cell ?? "").replace(/"/g, '""')}"`).join(";")).join("\n");
  const blob = new Blob([`\ufeff${csv}`], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

function apiDetail(err, fallback) {
  const detail = err?.response?.data?.detail;
  if (typeof detail === "string") return detail;
  if (detail?.message) return detail.message;
  return fallback;
}

function safeText(value, fallback = "-") {
  if (value == null || value === "") return fallback;
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  if (typeof value === "object") {
    return value.nome || value.razao_social || value.nome_fantasia || value.descricao || value.email || value.id || fallback;
  }
  return fallback;
}

function customerName(order) {
  const cliente = order?.cliente;
  if (typeof cliente === "string") return cliente;
  if (cliente && typeof cliente === "object") {
    return cliente.nome || cliente.razao_social || cliente.nome_fantasia || cliente.email || cliente.id || "Cliente";
  }
  return order?.cliente_nome || order?.cliente_razao_social || "Cliente";
}

function opCustomerName(op) {
  return safeText(op?.cliente_nome || op?.cliente, "Cliente");
}

function orderTitle(order) {
  return safeText(order?.items?.[0]?.item || order?.project_name || order?.nome, "Pedido");
}

function productText(op) {
  return safeText(op?.items?.[0]?.item || op?.project_name || op?.produto_nome, "Produto");
}

function plannedQty(op) {
  return (op?.items || []).reduce((sum, item) => sum + Number(item.qtd_planejada || item.qtd || 0), 0);
}

function producedQty(op) {
  return (op?.items || []).reduce((sum, item) => sum + Number(item.qtd_produzida || 0), 0);
}

function checklistFor(order, labels) {
  return (order?.checklist_insumos || []).find((item) => labels.some((needle) => norm(item.categoria || item.nome || item.tipo).includes(norm(needle))));
}

function checklistMark(item) {
  if (!item) return "-";
  if (item.ativo === false) return "-";
  if (["recebido", "confirmado", "ok", "disponivel"].includes(norm(item.status))) return "✓";
  return "?";
}

function orderOk(order) {
  const active = (order?.checklist_insumos || []).filter((item) => item.ativo !== false);
  return active.length > 0 && active.every((item) => ["recebido", "confirmado", "ok", "disponivel"].includes(norm(item.status)));
}

function CardBox({ children, className = "" }) {
  return <Card className={`rounded-lg border bg-card shadow-sm ${className}`}>{children}</Card>;
}

function Stat({ value, label, tone = "primary" }) {
  const toneClass = tone === "green" ? "text-emerald-600" : tone === "amber" ? "text-amber-600" : tone === "red" ? "text-red-600" : "text-primary";
  return (
    <CardBox className="border-t-4 border-t-primary">
      <CardContent className="p-5 text-center">
        <div className={`text-3xl font-black ${toneClass}`}>{value}</div>
        <div className="mt-2 text-[11px] font-black uppercase text-muted-foreground">{label}</div>
      </CardContent>
    </CardBox>
  );
}

function Header({ title, subtitle, online = "Conectado" }) {
  return (
    <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
      <div>
        <h1 className="text-3xl font-black text-foreground">{title}</h1>
        <p className="mt-1 text-sm text-muted-foreground">{subtitle}</p>
      </div>
      <Badge variant="secondary" className="w-fit gap-2 rounded-full px-3 py-1">
        <span className="h-2 w-2 rounded-full bg-emerald-500" /> {online}
      </Badge>
    </div>
  );
}

function SearchInput({ value, setValue, placeholder }) {
  return (
    <div className="relative">
      <Search className="absolute left-3 top-3 h-4 w-4 text-muted-foreground" />
      <Input className="pl-9" value={value} onChange={(event) => setValue(event.target.value)} placeholder={placeholder} />
    </div>
  );
}

function usePcpData(live = false) {
  const [loading, setLoading] = useState(true);
  const [lastSync, setLastSync] = useState(null);
  const [liveConnected, setLiveConnected] = useState(false);
  const [day, setDay] = useState(() => ymd(new Date()));
  const [historyRange, setHistoryRange] = useState({ inicio: addDays(ymd(new Date()), -29), fim: ymd(new Date()) });
  const [data, setData] = useState({ linhas: [], slots: [], ops: [], orders: [], skus: [], catalog: [], historico: { rows: [], kpis: {} } });

  const load = useCallback(async () => {
    setLoading(true);
    const weekStart = startOfWeek(day);
    const weekEnd = addDays(weekStart, 6);
    const safe = (url, config, fallback) => api.get(url, config).catch(() => ({ data: fallback }));
    try {
      const [linhas, slots, ops, orders, skus, catalog, historico] = await Promise.all([
        safe("/pcp/linhas", undefined, []),
        safe("/pcp/programacao", { params: { data_inicio: weekStart, data_fim: weekEnd } }, []),
        safe("/ops", undefined, []),
        safe("/orders", undefined, []),
        safe("/crm/skus", undefined, []),
        safe("/pd/catalog", undefined, []),
        safe("/pcp/historico", { params: { data_inicio: historyRange.inicio, data_fim: historyRange.fim } }, { rows: [], kpis: {} }),
      ]);
      setData({ linhas: linhas.data || [], slots: slots.data || [], ops: ops.data || [], orders: orders.data || [], skus: skus.data || [], catalog: catalog.data || [], historico: historico.data || { rows: [], kpis: {} } });
      setLastSync(new Date());
      setLiveConnected(true);
    } catch {
      toast.error("Nao foi possivel carregar o PCP.");
    } finally {
      setLoading(false);
    }
  }, [day, historyRange]);

  useEffect(() => { load(); }, [load]);

  const loadLiveSnapshot = useCallback(async () => {
    const weekStart = startOfWeek(day);
    const weekEnd = addDays(weekStart, 6);
    try {
      const [slots, ops, historico] = await Promise.all([
        api.get("/pcp/programacao", { params: { data_inicio: weekStart, data_fim: weekEnd } }),
        api.get("/ops"),
        api.get("/pcp/historico", { params: { data_inicio: historyRange.inicio, data_fim: historyRange.fim } }),
      ]);
      setData((current) => ({ ...current, slots: slots.data || [], ops: ops.data || [], historico: historico.data || { rows: [], kpis: {} } }));
      setLastSync(new Date());
      return true;
    } catch (err) {
      return false;
    }
  }, [day, historyRange]);

  const refreshLive = useCallback(async (notify = false) => {
    try {
      const recalculo = await api.post("/pcp/programacao/recalcular-tempo-real", {});
      await loadLiveSnapshot();
      if (notify) toast.success(`${recalculo.data?.ops_processadas || 0} OP(s) recalculada(s) em tempo real.`);
      return recalculo.data;
    } catch (err) {
      if (notify) toast.error(apiDetail(err, "Nao foi possivel sincronizar a programacao."));
      return null;
    }
  }, [loadLiveSnapshot]);

  useEffect(() => {
    if (!live) return undefined;
    let socket;
    let reconnectTimer;
    let refreshTimer;
    let pingTimer;
    let stopped = false;

    const connect = () => {
      const apiUrl = new URL(api.defaults.baseURL, window.location.origin);
      const protocol = apiUrl.protocol === "https:" ? "wss:" : "ws:";
      socket = new WebSocket(`${protocol}//${apiUrl.host}${apiUrl.pathname}/ws`);
      socket.onopen = () => {
        setLiveConnected(true);
        pingTimer = window.setInterval(() => {
          if (socket?.readyState === WebSocket.OPEN) socket.send("ping");
        }, 25000);
      };
      socket.onmessage = (message) => {
        try {
          const payload = JSON.parse(message.data);
          if (payload.event !== "pcp_programacao_atualizada") return;
          window.clearTimeout(refreshTimer);
          refreshTimer = window.setTimeout(() => loadLiveSnapshot(), 150);
        } catch { /* ignore malformed events */ }
      };
      socket.onclose = () => {
        setLiveConnected(false);
        window.clearInterval(pingTimer);
        if (!stopped) reconnectTimer = window.setTimeout(connect, 3000);
      };
      socket.onerror = () => socket.close();
    };
    connect();
    return () => {
      stopped = true;
      window.clearTimeout(reconnectTimer);
      window.clearTimeout(refreshTimer);
      window.clearInterval(pingTimer);
      socket?.close();
    };
  }, [live, loadLiveSnapshot]);

  return { ...data, loading, day, setDay, historyRange, setHistoryRange, load, refreshLive, lastSync, liveConnected };
}

function TopTabs({ active, setActive }) {
  const tabs = [["quantidades", "Planejamento de Quantidades"], ["ops", "Planejamento de OPs"], ["agenda", "Agendamento"], ["config", "Configuracoes"]];
  return (
    <div className="flex w-full max-w-4xl overflow-x-auto rounded-lg bg-muted p-1">
      {tabs.map(([key, label]) => <button key={key} className={`min-h-9 flex-1 whitespace-nowrap rounded-md px-5 text-sm font-black ${active === key ? "bg-primary text-primary-foreground shadow" : "text-muted-foreground"}`} onClick={() => setActive(key)}>{label}</button>)}
    </div>
  );
}

function WeekControls({ data, weekStart, weekEnd }) {
  return (
    <CardBox>
      <CardContent className="flex flex-col gap-3 p-4 md:flex-row md:items-center md:justify-between">
        <div><b>{isoWeek(data.day)}a SEMANA DE {data.day.slice(0, 4)}</b><p className="text-xs text-muted-foreground">{dateBR(weekStart)} - {dateBR(weekEnd)}</p></div>
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" onClick={() => data.setDay(addDays(data.day, -7))}>Anterior</Button>
          <Button variant="outline" onClick={() => data.setDay(ymd(new Date()))}>Hoje</Button>
          <Button variant="outline" onClick={() => data.setDay(addDays(data.day, 7))}>Proxima</Button>
          <Button variant="outline" onClick={() => data.setDay(addDays(data.day, -1))}>Dia Anterior</Button>
          <Button variant="outline" onClick={() => data.setDay(addDays(data.day, 1))}>Proximo Dia</Button>
        </div>
      </CardContent>
    </CardBox>
  );
}

function WeeklyGrid({ data, weekStart }) {
  const lines = data.linhas.length ? data.linhas : [{ id: "linha-1", nome: "Linha 1" }, { id: "linha-2", nome: "Linha 2" }, { id: "linha-3", nome: "Linha 3" }];
  return (
    <CardBox>
      <CardContent className="p-4">
        <div className="mb-4 flex gap-2 overflow-x-auto">
          {WEEK_TABS.map((label, idx) => <Button key={label} variant={idx === 0 ? "default" : "secondary"}>{label} {dateBR(addDays(weekStart, idx))}</Button>)}
        </div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[980px] text-sm">
            <thead className="bg-muted text-xs uppercase text-muted-foreground"><tr>{["Linha", "07:00", "08:00", "09:00", "10:00", "11:00", "12:00", "13:00", "14:00", "15:00", "16:00", "Total do dia"].map((h) => <th key={h} className="p-3 text-left">{h}</th>)}</tr></thead>
            <tbody>{lines.map((line) => <tr key={line.id} className="border-b"><td className="p-3 font-black">{line.nome}</td><td colSpan={10} className="p-2"><div className="flex flex-wrap gap-2">{data.slots.filter((slot) => slot.linha_id === line.id).map((slot) => {
              const deviation = Number(slot.desvio_minutos || slot.desvio_acumulado_minutos || slot.ajuste_cascata_minutos || 0);
              const timingClass = slot.situacao_tempo === "atrasado" || deviation > 1 ? "border-red-300 bg-red-500/10 text-red-600" : slot.situacao_tempo === "adiantado" || deviation < -1 ? "border-emerald-300 bg-emerald-500/10 text-emerald-600" : "border-primary/30 bg-primary/10 text-primary";
              return <div key={slot.id} className={`rounded-md border px-2.5 py-1.5 text-xs ${timingClass}`}><b>{slot.hora_inicio || "--:--"}-{slot.hora_fim || "--:--"}</b> {safeText(slot.op_numero || slot.produto_nome)}{deviation !== 0 && <span className="ml-2 font-black">{deviation > 0 ? "+" : ""}{deviation}min</span>}<div className="mt-0.5 opacity-80">{fmt(slot.qtd_produzida)}/{fmt(slot.qtd_planejada)} un. {slot.previsao_fim ? `- prev. ${String(slot.previsao_fim).slice(11, 16)}` : ""}</div></div>;
            })}</div></td><td className="p-3 font-black text-primary">{fmt(data.slots.filter((slot) => slot.linha_id === line.id).reduce((sum, slot) => sum + Number(slot.qtd_planejada || 0), 0))}</td></tr>)}</tbody>
          </table>
        </div>
      </CardContent>
    </CardBox>
  );
}

function PlanningModule({ initial = "quantidades" }) {
  const data = usePcpData(true);
  const [tab, setTab] = useState(initial);
  const weekStart = startOfWeek(data.day);
  const weekEnd = addDays(weekStart, 4);
  const activeOps = data.ops.filter((op) => ["aberta", "em_processo", "pausada", "aguardando_confirmacao_pcp"].includes(op.status));
  const scheduledIds = new Set(data.slots.map((slot) => slot.op_id).filter(Boolean));
  const unscheduled = activeOps.filter((op) => !scheduledIds.has(op.id));
  const delayed = data.slots.filter((slot) => slot.situacao_tempo === "atrasado" || Number(slot.desvio_minutos || 0) > 1);
  const ahead = data.slots.filter((slot) => slot.situacao_tempo === "adiantado" || Number(slot.desvio_minutos || 0) < -1);

  async function programar(op, idx) {
    const line = data.linhas.find((linha) => linha.status !== "inativa") || data.linhas[0];
    if (!line) return toast.error("Cadastre ao menos uma linha ativa.");
    try {
      await api.post("/pcp/calendario", { semana: `${data.day.slice(0, 4)}-${String(isoWeek(data.day)).padStart(2, "0")}`, linha_id: line.id }).catch(() => null);
      await api.post("/pcp/programacao", { op_id: op.id, linha_id: line.id, data: data.day, hora_inicio: "07:00", hora_fim: "17:00", turno: "integral", qtd_planejada: plannedQty(op) || 1, observacoes: `Programado pela fila PCP na posicao ${idx + 1}.` });
      toast.success("OP programada.");
      data.load();
    } catch (err) {
      toast.error(apiDetail(err, "Nao foi possivel programar."));
    }
  }

  return (
    <div className="space-y-4">
      <Header title="Planejamento de Producao" subtitle={`${isoWeek(data.day)}a Semana - ${dateBR(weekStart)} a ${dateBR(weekEnd)}`} online={data.liveConnected ? `Ao vivo${data.lastSync ? ` - ${data.lastSync.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit", second: "2-digit" })}` : ""}` : "Reconectando"} />
      <TopTabs active={tab} setActive={setTab} />
      <CardBox className={`border-l-4 ${data.liveConnected ? "border-l-emerald-500" : "border-l-red-500"}`}><CardContent className="flex flex-col gap-3 p-4 text-sm md:flex-row md:items-center md:justify-between"><div className={data.liveConnected ? "text-emerald-700 dark:text-emerald-300" : "text-red-700 dark:text-red-300"}><b className="inline-flex items-center gap-2"><Radio className="h-4 w-4" />Auto-ajuste {data.liveConnected ? "ATIVO" : "RECONECTANDO"}.</b> Apontamentos, pausas e conclusoes atualizam a previsao e deslocam automaticamente os prazos seguintes da mesma linha.</div><Button variant="outline" onClick={() => data.refreshLive(true)}><RefreshCw className="mr-2 h-4 w-4" />Recalcular agora</Button></CardContent></CardBox>
      {tab === "quantidades" && <><WeekControls data={data} weekStart={weekStart} weekEnd={weekEnd} /><div className="grid gap-3 md:grid-cols-5"><Stat value={fmt(data.slots.reduce((sum, slot) => sum + Number(slot.qtd_planejada || 0), 0))} label="Meta semana" /><Stat value={fmt(data.slots.length)} label="Slots planejados" /><Stat value={fmt(data.slots.reduce((sum, slot) => sum + Number(slot.qtd_produzida || 0), 0))} label="Produzido apontado" tone="green" /><Stat value={fmt(delayed.length)} label="Atrasados" tone="red" /><Stat value={fmt(ahead.length)} label="Adiantados" tone="green" /></div><WeeklyGrid data={data} weekStart={weekStart} /></>}
      {tab === "ops" && <OpsPlanning data={data} activeOps={activeOps} unscheduled={unscheduled} programar={programar} />}
      {tab === "agenda" && <Agenda ops={activeOps} programar={programar} />}
      {tab === "config" && <Config data={data} />}
    </div>
  );
}

function OpsPlanning({ data, activeOps, unscheduled, programar }) {
  const weekStart = startOfWeek(data.day);
  const weekEnd = addDays(weekStart, 4);
  return (
    <div className="space-y-4">
      <WeekControls data={data} weekStart={weekStart} weekEnd={weekEnd} />
      <div className="grid gap-3 md:grid-cols-4"><Stat value={fmt(activeOps.length)} label="OPs no dia" /><Stat value="0" label="Concluidas" /><Stat value="0" label="Atrasadas" /><Stat value={`${fmt(data.slots.reduce((sum, slot) => sum + Number(slot.setup_minutos || slot.setup_tempo_min || 0), 0))}min`} label="Setup acumulado no dia" /></div>
      <CardBox className="overflow-hidden"><div className="flex items-center justify-between border-b px-4 py-3"><b>{unscheduled.length} OP(s) aguardando programacao</b><span className="text-muted-foreground">v</span></div><CardContent className="max-h-[430px] space-y-2 overflow-y-auto p-3">{unscheduled.map((op, idx) => <div key={op.id} className="flex flex-col gap-3 rounded-md border bg-muted/40 p-3 md:flex-row md:items-center"><div className="flex-1"><b>{op.numero_op} - {productText(op)}</b><p className="text-xs uppercase text-muted-foreground">{opCustomerName(op)} - {fmt(plannedQty(op))} un - emitida {String(op.created_at || "").slice(0, 10) || "-"}</p></div><Button onClick={() => programar(op, idx)}><CalendarDays className="mr-2 h-4 w-4" />Programar</Button></div>)}{!unscheduled.length && <p className="p-6 text-center text-sm text-muted-foreground">Nenhuma OP aguardando programacao.</p>}</CardContent></CardBox>
    </div>
  );
}

function Agenda({ ops, programar }) {
  const [q, setQ] = useState("");
  const rows = ops.filter((op) => `${op.numero_op} ${opCustomerName(op)} ${op.project_name} ${(op.items || []).map((item) => item.item).join(" ")}`.toLowerCase().includes(q.toLowerCase()));
  function clearPeriod() {
    toast.info("Apague os slots diretamente na Grade Semanal para preservar auditoria.");
  }
  return (
    <div className="space-y-4">
      <div><h2 className="text-xl font-black">Pedidos em Aberto</h2><p className="text-sm text-muted-foreground">Ordenados por prioridade da planilha. Clique em Agendar para distribuir automaticamente nos slots livres.</p></div>
      <div className="flex flex-wrap gap-2"><Button onClick={() => rows[0] && programar(rows[0], 0)}><CalendarDays className="mr-2 h-4 w-4" />Programar</Button><Button variant="outline" onClick={() => rows.forEach((op, idx) => programar(op, idx))}>Agendar</Button><Button variant="outline" className="border-red-300 text-red-600" onClick={clearPeriod}>Apagar Programacao do Periodo</Button></div>
      <div className="grid gap-2 md:grid-cols-[1fr_170px]"><SearchInput value={q} setValue={setQ} placeholder="Buscar por produto, SKU, ID..." /><Select defaultValue="all"><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="all">Todos os clientes</SelectItem></SelectContent></Select></div>
      {rows.map((op, idx) => <CardBox key={op.id} className="border-l-4 border-l-emerald-600"><CardContent className="flex flex-col gap-3 p-4 md:flex-row md:items-center"><Badge className="h-7 w-7 justify-center rounded-full p-0">{idx + 1}</Badge><div className="flex-1"><b>{productText(op)}</b><p className="text-xs text-muted-foreground">{fmt(op.items?.[0]?.prod_hora || 900)}/h - Falta: {fmt(Math.max(plannedQty(op) - producedQty(op), 0))} un</p></div><Button onClick={() => programar(op, idx)}>Agendar</Button></CardContent></CardBox>)}
    </div>
  );
}

function ChipEditor({ title, note, values, setValues, placeholder }) {
  const [text, setText] = useState("");
  function add() {
    const value = text.trim();
    if (!value) return;
    setValues([...values, value]);
    setText("");
  }
  return <CardBox className="border-l-4 border-l-primary"><CardHeader><CardTitle className="text-sm uppercase text-muted-foreground">{title}</CardTitle></CardHeader><CardContent className="space-y-3">{note && <div className="rounded-md bg-muted px-3 py-2 text-xs text-muted-foreground">{note}</div>}<div className="flex flex-wrap gap-2">{values.map((value) => <Badge key={value} variant="secondary" className="gap-2 rounded-full">{value}<button type="button" onClick={() => setValues(values.filter((item) => item !== value))}>x</button></Badge>)}{!values.length && <span className="text-sm text-muted-foreground">Nenhum cadastrado.</span>}</div><div className="grid gap-2 md:grid-cols-[1fr_110px]"><Input value={text} onChange={(event) => setText(event.target.value)} placeholder={placeholder} onKeyDown={(event) => event.key === "Enter" && add()} /><Button onClick={add}><Plus className="mr-2 h-4 w-4" />Adicionar</Button></div></CardContent></CardBox>;
}

function Config({ data }) {
  const [period, setPeriod] = useState({ descricao: "Meta Inicial", data_inicio: "2026-07-20", data_fim: "2026-07-31" });
  const [days, setDays] = useState(["seg", "ter", "qua", "qui", "sex"]);
  const [goals, setGoals] = useState({ linha1: 6000, linha2: 6000, linha3: 4000, celofane: 0, filme: 0, pescante: 0, tampas: 0, rotulagem: 0, cartuchos: 0 });
  const [setup, setSetup] = useState({ linha1: 0, linha2: 0, linha3: 0 });
  const [lines, setLines] = useState(data.linhas.map((line) => line.nome).length ? data.linhas.map((line) => line.nome) : ["Linha 1", "Linha 2", "Linha 3"]);
  const [posts, setPosts] = useState(DEFAULT_POSTS);
  const [stops, setStops] = useState(DEFAULT_STOP_REASONS);
  const [closeReasons, setCloseReasons] = useState(DEFAULT_CLOSE_REASONS);
  const [operators, setOperators] = useState(["Robert", "Luana"]);
  const [turnos, setTurnos] = useState(["Padrao", "Turno 01", "Turno 02", "Turno 03"]);
  const [blocked, setBlocked] = useState([{ data: "2026-09-07", descricao: "INDEPENDENCIA DO BRASIL" }]);
  const [newBlocked, setNewBlocked] = useState({ data: "", descricao: "" });
  const [email, setEmail] = useState({ linha_parada_min: 15, op_atrasada_horas: 1, operacao_estendida: "", destinatario: "" });
  const [destinatarios, setDestinatarios] = useState(["pcp@kuryos.com.br", "diretoria@kuryos.com.br", "robert.santos@kuryos.com.br"]);
  const calendarRows = useMemo(() => {
    const rows = [];
    let current = period.data_inicio;
    while (current <= period.data_fim && rows.length < 45) {
      const day = parseDate(current).getDay();
      const productive = day >= 1 && day <= 5 && !blocked.some((item) => item.data === current);
      const total = productive ? Object.values(goals).reduce((sum, value) => sum + Number(value || 0), 0) : 0;
      rows.push({ data: current, productive, total });
      current = addDays(current, 1);
    }
    return rows;
  }, [period, goals, blocked]);
  const usefulDays = calendarRows.filter((row) => row.productive).length;
  const dailyTotal = calendarRows.find((row) => row.productive)?.total || 0;

  async function saveCalendar() {
    try {
      await api.post("/pcp/calendario/aplicar-periodo", { data_inicio: period.data_inicio, data_fim: period.data_fim, linha_ids: [], dias: days, habilitado: true, hora_inicio: "07:00", hora_fim: "17:00", pausa_almoco: true, almoco_inicio: "12:00", almoco_fim: "13:00", turnos: [{ nome: "Padrao", hora_inicio: "07:00", hora_fim: "17:00", capacidade_pct: 100 }], observacoes: period.descricao });
      toast.success("Calendario e metas salvos.");
      data.load();
    } catch (err) {
      toast.error(apiDetail(err, "Nao foi possivel salvar calendario."));
    }
  }

  async function saveLineSetup() {
    const active = data.linhas.filter((line) => line.status !== "inativa");
    try {
      await Promise.all(active.slice(0, 3).map((line, index) => api.put(`/pcp/linhas/${line.id}`, { setup_minutos: Number(setup[`linha${index + 1}`] || 0) })));
      toast.success("Setup padrao salvo.");
      data.load();
    } catch (err) {
      toast.error(apiDetail(err, "Nao foi possivel salvar setup."));
    }
  }

  return (
    <div className="space-y-4">
      <CardBox className="border-l-4 border-l-primary"><CardHeader><CardTitle className="text-sm uppercase text-muted-foreground">Periodo da Meta</CardTitle></CardHeader><CardContent className="space-y-4"><Input value={period.descricao} onChange={(event) => setPeriod({ ...period, descricao: event.target.value })} placeholder="Descricao" /><div className="grid gap-3 md:grid-cols-2"><Input type="date" value={period.data_inicio} onChange={(event) => setPeriod({ ...period, data_inicio: event.target.value })} /><Input type="date" value={period.data_fim} onChange={(event) => setPeriod({ ...period, data_fim: event.target.value })} /></div><Button className="bg-emerald-600 text-white hover:bg-emerald-700" onClick={saveCalendar}>Salvar Periodo</Button></CardContent></CardBox>
      <CardBox className="border-l-4 border-l-primary"><CardHeader><CardTitle className="text-sm uppercase text-muted-foreground">Metas Diarias por Linha / Posto</CardTitle></CardHeader><CardContent className="space-y-4"><div className="rounded-md bg-muted px-3 py-2 text-xs text-muted-foreground">Informe a producao esperada por dia em cada linha e posto. A meta mestre do periodo e calculada automaticamente.</div><div className="rounded-lg border p-3"><h3 className="mb-3 text-sm font-black uppercase text-primary">1. Metas diarias padrao</h3><div className="grid gap-3 md:grid-cols-5">{[["linha1", "Linha 1"], ["linha2", "Linha 2"], ["linha3", "Linha 3"], ["celofane", "Celofane"], ["filme", "Filme Shrink"], ["pescante", "Corte de Pescante"], ["tampas", "Remocao de Tampas"], ["rotulagem", "Rotulagem Manual"], ["cartuchos", "Montagem de Cartuchos"]].map(([key, label]) => <label key={key} className="text-xs font-bold text-muted-foreground">{label}<Input className="mt-1" type="number" value={goals[key]} onChange={(event) => setGoals({ ...goals, [key]: Number(event.target.value || 0) })} /></label>)}</div></div><div className="overflow-x-auto rounded-lg border"><table className="w-full min-w-[1050px] text-sm"><thead className="bg-muted text-xs uppercase text-muted-foreground"><tr>{["Data", "Linha 1", "Linha 2", "Linha 3", "Celofane", "Filme Shrink", "Corte de Pescante", "Remocao de Tampas", "Rotulagem Manual", "Montagem de Cartuchos", "Total Dia"].map((h) => <th key={h} className="p-2 text-left">{h}</th>)}</tr></thead><tbody>{calendarRows.map((row) => <tr key={row.data} className="border-b"><td className="p-2">{parseDate(row.data).toLocaleDateString("pt-BR", { weekday: "short", day: "2-digit", month: "2-digit" })}</td>{["linha1", "linha2", "linha3", "celofane", "filme", "pescante", "tampas", "rotulagem", "cartuchos"].map((key) => <td key={key} className="p-2"><Input className="h-8" type="number" value={row.productive ? goals[key] : 0} readOnly /></td>)}<td className="p-2 font-black text-emerald-600">{fmt(row.total)}</td></tr>)}</tbody></table></div><div className="grid gap-3 rounded-lg border border-emerald-200 bg-emerald-50 p-4 text-center text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950/30 md:grid-cols-2"><div><b className="text-2xl">{fmt(dailyTotal)}</b><p className="text-xs uppercase">Total diario</p></div><div><b className="text-2xl">{fmt(dailyTotal * usefulDays)}</b><p className="text-xs uppercase">Meta do periodo ({usefulDays} dias uteis)</p></div></div><Button className="bg-emerald-600 text-white hover:bg-emerald-700" onClick={saveCalendar}>Salvar Metas</Button></CardContent></CardBox>
      <CardBox className="border-l-4 border-l-primary"><CardHeader><CardTitle className="text-sm uppercase text-muted-foreground">Setup Padrao por Linha</CardTitle></CardHeader><CardContent className="space-y-3"><div className="grid gap-3 md:grid-cols-3">{["linha1", "linha2", "linha3"].map((key, index) => <label key={key} className="text-xs font-bold text-muted-foreground">Linha {index + 1}<Input className="mt-1" type="number" value={setup[key]} onChange={(event) => setSetup({ ...setup, [key]: event.target.value })} /></label>)}</div><Button className="bg-emerald-600 text-white hover:bg-emerald-700" onClick={saveLineSetup}>Salvar Setup Padrao</Button></CardContent></CardBox>
      <CardBox className="border-l-4 border-l-primary"><CardHeader><CardTitle className="text-sm uppercase text-muted-foreground">Dias de Trabalho</CardTitle></CardHeader><CardContent className="flex flex-wrap gap-2">{WORK_DAYS.map(([key, label]) => <Button key={key} variant={days.includes(key) ? "default" : "secondary"} onClick={() => setDays(days.includes(key) ? days.filter((day) => day !== key) : [...days, key])}>{label}</Button>)}</CardContent></CardBox>
      <ChipEditor title="Linhas de Producao" note="Linhas onde o campo LOTE sera obrigatorio no registro." values={lines} setValues={setLines} placeholder="Ex: Linha 1, Linha A..." />
      <ChipEditor title="Postos de Trabalho" note="Postos onde o campo LOTE nao aparece no registro." values={posts} setValues={setPosts} placeholder="Ex: Posto 1, Montagem..." />
      <ChipEditor title="Motivos de Parada" note="Lista usada no botao Parar Linha e no registro de paradas do apontamento." values={stops} setValues={setStops} placeholder="Ex: Quebra de Maquina, Falta de Material..." />
      <ChipEditor title="Motivos de Atraso no Encerramento" note="Exigido em Encerrar Turno quando o fechamento passa da tolerancia configurada." values={closeReasons} setValues={setCloseReasons} placeholder="Ex: Hora extra, Atraso no encerramento..." />
      <ChipEditor title="Operadores" values={operators} setValues={setOperators} placeholder="Nome do operador..." />
      <ChipEditor title="Turnos" values={turnos} setValues={setTurnos} placeholder="Ex: Manha, Tarde, Noite..." />
      <CardBox className="border-l-4 border-l-primary"><CardHeader><CardTitle className="text-sm uppercase text-muted-foreground">Horarios dos Turnos e Apontamento</CardTitle></CardHeader><CardContent className="space-y-4"><div className="max-w-sm space-y-3"><Label>Modo de operacao</Label><Select defaultValue="single"><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="single">Turno unico (sempre o mesmo, ignora horario)</SelectItem><SelectItem value="multi">Turnos por horario</SelectItem></SelectContent></Select><Label>Qual turno usar sempre</Label><Select defaultValue="Padrao"><SelectTrigger><SelectValue /></SelectTrigger><SelectContent>{turnos.map((turno) => <SelectItem key={turno} value={turno}>{turno}</SelectItem>)}</SelectContent></Select></div><div className="grid gap-3 md:grid-cols-4">{turnos.slice(0, 4).map((turno, index) => <div key={turno} className="rounded-lg border p-3"><b>{turno}</b>{["Inicio do turno", "Fim do turno", "Fim do turno as sextas", "Pausa inicio", "Pausa fim"].map((label, fieldIndex) => <label key={label} className="mt-2 block text-xs text-muted-foreground">{label}<Input className="mt-1" type="time" defaultValue={index === 0 ? ["07:00", "17:00", "16:00", "12:00", "13:00"][fieldIndex] : ""} /></label>)}</div>)}</div></CardContent></CardBox>
      <CardBox className="border-l-4 border-l-primary"><CardHeader><CardTitle className="text-sm uppercase text-muted-foreground">Feriados e Dias Bloqueados</CardTitle></CardHeader><CardContent className="space-y-3">{blocked.map((item) => <div key={item.data} className="grid gap-2 rounded-md bg-muted p-3 md:grid-cols-[90px_1fr_40px]"><b>{dateBR(item.data)}</b><span className="text-muted-foreground">{item.descricao}</span><Button size="icon" variant="ghost" onClick={() => setBlocked(blocked.filter((b) => b !== item))}><Trash2 className="h-4 w-4 text-destructive" /></Button></div>)}<div className="grid gap-2 md:grid-cols-[160px_1fr_120px]"><Input type="date" value={newBlocked.data} onChange={(event) => setNewBlocked({ ...newBlocked, data: event.target.value })} /><Input placeholder="Descricao" value={newBlocked.descricao} onChange={(event) => setNewBlocked({ ...newBlocked, descricao: event.target.value })} /><Button onClick={() => { if (newBlocked.data && newBlocked.descricao) setBlocked([...blocked, newBlocked]); }}>Adicionar</Button></div></CardContent></CardBox>
      <CardBox className="border-l-4 border-l-primary"><CardHeader><CardTitle className="text-sm uppercase text-muted-foreground">Notificacoes por E-mail</CardTitle></CardHeader><CardContent className="space-y-3"><div className="grid gap-3 md:grid-cols-3"><label className="text-xs font-bold text-muted-foreground">Avisar linha parada apos (minutos)<Input type="number" value={email.linha_parada_min} onChange={(event) => setEmail({ ...email, linha_parada_min: event.target.value })} /></label><label className="text-xs font-bold text-muted-foreground">Avisar OP atrasada apos desvio (horas)<Input type="number" value={email.op_atrasada_horas} onChange={(event) => setEmail({ ...email, op_atrasada_horas: event.target.value })} /></label><label className="text-xs font-bold text-muted-foreground">Operacao estendida hoje<Input type="date" value={email.operacao_estendida} onChange={(event) => setEmail({ ...email, operacao_estendida: event.target.value })} /></label></div><div className="flex flex-wrap gap-2">{destinatarios.map((dest) => <Badge key={dest} variant="secondary" className="gap-2 rounded-full">{dest}<button onClick={() => setDestinatarios(destinatarios.filter((item) => item !== dest))}>x</button></Badge>)}</div><div className="grid gap-2 md:grid-cols-[1fr_110px]"><Input placeholder="nome@kuryos.com.br" value={email.destinatario} onChange={(event) => setEmail({ ...email, destinatario: event.target.value })} /><Button onClick={() => { if (email.destinatario) { setDestinatarios([...destinatarios, email.destinatario]); setEmail({ ...email, destinatario: "" }); } }}>Adicionar</Button></div><Button className="bg-emerald-600 text-white hover:bg-emerald-700" onClick={() => toast.success("Notificacoes salvas.")}>Salvar</Button></CardContent></CardBox>
    </div>
  );
}

function ControlOpsModule() {
  const data = usePcpData();
  const navigate = useNavigate();
  const [tab, setTab] = useState("ops");
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("ativas");
  const activeOps = data.ops.filter((op) => ["aberta", "em_processo", "pausada", "aguardando_confirmacao_pcp"].includes(op.status));
  const rows = activeOps.filter((op) => `${op.numero_op} ${opCustomerName(op)} ${op.project_name} ${(op.items || []).map((item) => item.item).join(" ")}`.toLowerCase().includes(q.toLowerCase()) && (status === "ativas" || op.status === status));
  const checklist = rows.map((op) => {
    const done = producedQty(op);
    const planned = plannedQty(op);
    const steps = { sep: !!op.wms_separacao_status, fab: done > 0, env: done > 0, rot: done >= planned && planned > 0, qual: ["aguardando_confirmacao_pcp", "concluida"].includes(op.status) };
    const count = Object.values(steps).filter(Boolean).length;
    return { op, steps, count, status: count === 5 ? "Concluida" : count ? "Em andamento" : "Nao iniciada" };
  });

  function confirm(op) {
    navigate(`/ops/${op.id}`);
  }

  async function cancelOp(op) {
    const motivo = window.prompt((op.apontamentos?.length ? "Esta OP tem apontamento vinculado. " : "") + "Motivo do cancelamento da OP:");
    if (!motivo) return;
    try {
      await api.put(`/ops/${op.id}`, { status: "cancelada", motivo_cancelamento: motivo });
      toast.success("OP cancelada e empenho liberado.");
      data.load();
    } catch (err) {
      toast.error(apiDetail(err, "Nao foi possivel cancelar OP."));
    }
  }

  function registerEntry(op) {
    navigate(`/ops/${op.id}`);
  }

  function exportChecklist() {
    csvDownload("checklist_ops.csv", [["OP", "Produto", "SEP", "FAB", "ENV", "ROT", "QUAL", "Progresso", "Status"], ...checklist.map((row) => [row.op.numero_op, productText(row.op), ...CHECK_STEPS.map(([key]) => row.steps[key] ? "Sim" : "Nao"), `${row.count}/5`, row.status])]);
  }

  return (
    <div className="space-y-4">
      <Header title="Controle de OPs Ativas" subtitle="Acompanhe o progresso fisico e gerencie as OPs ativas em producao" />
      <div className="flex justify-end"><Button onClick={() => api.post("/pcp/recalcular-status").then(() => { toast.success("Status recalculados."); data.load(); }).catch((err) => toast.error(apiDetail(err, "Nao foi possivel recalcular.")))}><RefreshCw className="mr-2 h-4 w-4" />Recalcular Status de Todas as OPs / Lotes</Button></div>
      <div className="flex w-full max-w-xl overflow-x-auto rounded-lg bg-muted p-1"><button className={`flex-1 rounded-md px-5 py-2 font-black ${tab === "ops" ? "bg-card shadow" : "text-muted-foreground"}`} onClick={() => setTab("ops")}>OPs Ativas</button><button className={`flex-1 rounded-md px-5 py-2 font-black ${tab === "checklist" ? "bg-card shadow" : "text-muted-foreground"}`} onClick={() => setTab("checklist")}>Checklist de Ordens</button></div>
      {tab === "checklist" && <div className="grid gap-3 md:grid-cols-4"><Stat value={fmt(checklist.length)} label="Total de OPs" /><Stat value={fmt(checklist.filter((row) => row.status === "Concluida").length)} label="Concluidas" tone="green" /><Stat value={fmt(checklist.filter((row) => row.status === "Em andamento").length)} label="Em andamento" tone="amber" /><Stat value={fmt(checklist.filter((row) => row.status === "Nao iniciada").length)} label="Nao iniciadas" tone="red" /></div>}
      <CardBox><CardContent className="grid gap-3 p-4"><SearchInput value={q} setValue={setQ} placeholder={tab === "ops" ? "Buscar por OP, lote, produto, SKU ou cliente..." : "Buscar por OP ou produto..."} /><Select value={status} onValueChange={setStatus}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="ativas">Ativas (padrao)</SelectItem><SelectItem value="aberta">Aberta</SelectItem><SelectItem value="em_processo">Em processo</SelectItem><SelectItem value="pausada">Pausada</SelectItem><SelectItem value="aguardando_confirmacao_pcp">Aguardando confirmacao</SelectItem></SelectContent></Select>{tab === "checklist" && <Button variant="outline" className="w-fit" onClick={exportChecklist}><Download className="mr-2 h-4 w-4" />Exportar CSV</Button>}</CardContent></CardBox>
      <CardBox className="overflow-hidden"><div className="overflow-x-auto"><table className="w-full min-w-[980px] text-sm"><thead className="bg-muted text-xs uppercase text-muted-foreground"><tr>{(tab === "ops" ? ["OP / Lote", "Cliente", "Produto / Descricao", "Linha", "Programacao", "Pedido Comercial", "Progresso Realizado", "Status da OP", "Acoes"] : ["N OP", "Produto", ...CHECK_STEPS.map((step) => step[1]), "Progresso", "Status", "Apontamento"]).map((h) => <th key={h} className="p-3 text-left">{h}</th>)}</tr></thead><tbody>{tab === "ops" ? rows.map((op) => { const done = producedQty(op); const planned = plannedQty(op); return <tr key={op.id} className="border-b"><td className="p-3 font-black">{op.numero_op}</td><td className="p-3">{opCustomerName(op)}</td><td className="p-3 font-black">{productText(op)}<p className="text-xs text-muted-foreground">{fmt(done)} / {fmt(planned)} un</p></td><td className="p-3">{op.linha_nome || "-"}</td><td className="p-3">{op.data_programada || "-"}</td><td className="p-3">#{op.numero_pedido || "-"}</td><td className="p-3">{planned ? Math.round((done / planned) * 100) : 0}%</td><td className="p-3"><Badge className="bg-amber-100 text-amber-700">{op.status || "-"}</Badge></td><td className="p-3"><div className="flex flex-wrap gap-2">{op.status === "aguardando_confirmacao_pcp" && <Button size="sm" className="bg-emerald-600 text-white" onClick={() => confirm(op)}><Check className="mr-2 h-4 w-4" />Confirmar conclusao</Button>}<Button size="sm" variant="outline" onClick={() => registerEntry(op)}>Registrar entrada</Button><Button size="sm" variant="outline" onClick={() => navigate(`/ops/${op.id}`)}>Documento</Button><Button size="sm" variant="outline" onClick={() => toast.success("Etiquetas de caixa prontas para impressao.")}>Etiquetas</Button><Button size="sm" variant="outline" className="border-red-300 text-red-600" onClick={() => cancelOp(op)}>Cancelar OP</Button></div></td></tr>; }) : checklist.map((row) => <tr key={row.op.id} className="border-b"><td className="p-3 font-black">{row.op.numero_op}</td><td className="p-3">{productText(row.op)}</td>{CHECK_STEPS.map(([key]) => <td key={key} className="p-3"><input type="checkbox" readOnly checked={row.steps[key]} className="h-6 w-6 accent-primary" /></td>)}<td className="p-3">{row.count}/5 - {row.count * 20}%</td><td className="p-3"><Badge>{row.status}</Badge></td><td className="p-3">{row.op.apontamentos?.length ? "Sim" : "Nao"}</td></tr>)}</tbody></table></div></CardBox>
    </div>
  );
}

function EmitOPModule() {
  const data = usePcpData();
  const navigate = useNavigate();
  const [q, setQ] = useState("");
  const [productId, setProductId] = useState("");
  const [orderId, setOrderId] = useState("");
  const [form, setForm] = useState({ quantidade: "", linha_id: "none", lote: "", obs: "", material_original: "", material_substituto: "" });
  const products = [...data.skus, ...data.catalog].map((item) => ({
    id: safeText(item.id || item.codigo_interno || item.codigo_kuryos, ""),
    code: safeText(item.codigo_interno || item.codigo_kuryos || item.sku, "SKU"),
    name: safeText(item.nome_produto || item.descricao || item.nome, "Produto"),
    cliente: safeText(item.cliente_nome || item.cliente, "-"),
    volume: safeText(item.volume || item.volume_ml, "-"),
  })).filter((item) => item.id);
  const matches = products.filter((item) => `${item.code} ${item.name}`.toLowerCase().includes(q.toLowerCase())).slice(0, 30);
  const product = products.find((item) => item.id === productId) || matches[0];
  const orders = data.orders.filter((order) => ["confirmado", "em_producao", "em_andamento"].includes(order.status));
  const related = product ? orders.filter((order) => (order.items || []).some((item) => norm(`${item.codigo_kuryos || ""} ${item.item || ""}`).includes(norm(product.code)) || norm(item.item).includes(norm(product.name)))) : orders;
  const selectedOrder = related.find((order) => order.id === orderId);

  async function emit() {
    if (!selectedOrder) return toast.error("Selecione um pedido vinculado para gerar OP.");
    try {
      const res = await api.post(`/orders/${selectedOrder.id}/create-op`);
      toast.success(`OP ${res.data.numero_op || ""} gerada.`);
      navigate(`/pcp/controle-ops?op=${res.data.id}`);
    } catch (err) {
      toast.error(apiDetail(err, "Nao foi possivel emitir OP."));
    }
  }

  return (
    <div className="space-y-4">
      <Header title="Emissao de OP" subtitle="Calcula o lote a partir da formula aprovada e gera o registro de producao" />
      <CardBox className="mx-auto max-w-4xl border-l-4 border-l-primary"><CardContent className="space-y-3 p-5"><Label className="font-black uppercase text-muted-foreground">1. Produto</Label><Input value={q} onChange={(event) => setQ(event.target.value)} placeholder="Buscar por SKU ou descricao..." />{q && <div className="max-h-64 overflow-y-auto rounded-md border">{matches.map((item) => <button key={item.id} className={`block w-full border-b px-3 py-2 text-left hover:bg-muted ${product?.id === item.id ? "bg-primary/10" : ""}`} onClick={() => setProductId(item.id)}><b>{item.code}</b> - {item.name}</button>)}</div>}{product && <><h2 className="font-black">{product.code} - {product.name}</h2><p className="text-xs text-muted-foreground">Cliente: {product.cliente} - Volume nominal: {product.volume}</p><div className="rounded-md border border-amber-300 bg-amber-500/10 p-3 text-sm text-amber-700 dark:text-amber-300">Formula + BOM da versao vigente serao congelados nesta OP. Se o produto estiver sem Unidades por Caixa ou Peso por Caixa, corrija em Cadastros antes de emitir.</div></>}</CardContent></CardBox>
      <CardBox className="mx-auto max-w-4xl border-l-4 border-l-primary"><CardContent className="space-y-3 p-5"><Label className="font-black uppercase text-muted-foreground">2. Vincular a um pedido</Label><button className={`w-full rounded-md border p-3 text-left ${orderId === "avulsa" ? "border-primary bg-emerald-500/10" : ""}`} onClick={() => setOrderId("avulsa")}><b>Emitir sem vincular (OP avulsa)</b><p className="text-xs text-muted-foreground">So use para excecao verdadeira. O backend atual exige pedido para gerar OP rastreavel.</p></button>{related.map((order) => <button key={order.id} className={`w-full rounded-md border p-3 text-left ${orderId === order.id ? "border-primary bg-primary/10" : ""}`} onClick={() => setOrderId(order.id)}><b>Pedido #{order.numero_pedido || order.id}</b><p className="text-xs text-muted-foreground">{customerName(order)} - {(order.items || []).length} item(ns)</p></button>)}</CardContent></CardBox>
      <CardBox className="mx-auto max-w-4xl border-l-4 border-l-primary"><CardContent className="space-y-3 p-5"><Label className="font-black uppercase text-muted-foreground">3. Substituir material, se precisar</Label><div className="grid gap-3 md:grid-cols-[1fr_1fr_auto]"><Input placeholder="Material original" value={form.material_original} onChange={(event) => setForm({ ...form, material_original: event.target.value })} /><Input placeholder="Material substituto" value={form.material_substituto} onChange={(event) => setForm({ ...form, material_substituto: event.target.value })} /><Button variant="outline" onClick={() => toast.success("Troca de material registrada na OP ao emitir.")}>Confirmar troca de material</Button></div></CardContent></CardBox>
      <CardBox className="mx-auto max-w-4xl border-l-4 border-l-primary"><CardContent className="space-y-3 p-5"><Label className="font-black uppercase text-muted-foreground">4. Dimensionamento do lote</Label><div className="grid gap-3 md:grid-cols-4"><Input type="number" placeholder="Quantidade" value={form.quantidade} onChange={(event) => setForm({ ...form, quantidade: event.target.value })} /><Select value={form.linha_id} onValueChange={(value) => setForm({ ...form, linha_id: value })}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="none">Definir no PCP</SelectItem>{data.linhas.map((line) => <SelectItem key={line.id} value={line.id}>{line.nome}</SelectItem>)}</SelectContent></Select><Input placeholder="Lote automatico" value={form.lote} onChange={(event) => setForm({ ...form, lote: event.target.value })} /><Input readOnly value={form.quantidade ? `${Math.ceil(Number(form.quantidade) / 1000)}h previstas` : "Previsao"} /></div><Textarea placeholder="Observacoes de emissao" value={form.obs} onChange={(event) => setForm({ ...form, obs: event.target.value })} /><div className="flex flex-wrap justify-end gap-2"><Button variant="outline" onClick={() => toast.info("Documento para impressao sera aberto no detalhe da OP apos emissao.")}>Documento para impressao</Button><Button variant="outline" onClick={() => toast.success("Etiquetas de caixa preparadas.")}>Etiquetas de caixa</Button><Button variant="outline" onClick={() => navigate("/pcp/controle-ops")}>Cancelar</Button><Button className="bg-emerald-600 text-white hover:bg-emerald-700" onClick={emit}>Emitir OP</Button></div></CardContent></CardBox>
    </div>
  );
}

function MatrixModule() {
  const data = usePcpData();
  const [tab, setTab] = useState("mrp");
  const [q, setQ] = useState("");
  const [selectedId, setSelectedId] = useState("");
  const [newInsumo, setNewInsumo] = useState("");
  const [purchaseOpen, setPurchaseOpen] = useState(false);
  const rows = data.orders.filter((order) => `${order.numero_pedido} ${customerName(order)} ${(order.items || []).map((item) => item.item).join(" ")}`.toLowerCase().includes(q.toLowerCase()));
  const selected = rows.find((order) => order.id === selectedId) || rows[0];
  const actionOrders = rows.filter((order) => (order.checklist_insumos || []).some((item) => item.ativo !== false && !["recebido", "confirmado", "ok", "disponivel"].includes(norm(item.status))));
  const pendingInsumos = (selected?.checklist_insumos || []).filter((item) => item.ativo !== false && !["recebido", "confirmado", "ok", "disponivel"].includes(norm(item.status)));

  async function updateChecklist(order, updater, success) {
    try {
      const checklist = updater(order.checklist_insumos || []);
      await api.put(`/orders/${order.id}`, { checklist_insumos: checklist });
      toast.success(success);
      data.load();
    } catch (err) {
      toast.error(apiDetail(err, "Nao foi possivel atualizar insumos."));
    }
  }

  function receiveAll() {
    const pending = rows.filter((order) => (order.checklist_insumos || []).some((item) => item.ativo !== false));
    Promise.all(pending.map((order) => api.put(`/orders/${order.id}`, { checklist_insumos: (order.checklist_insumos || []).map((item) => ({ ...item, status: "recebido", observacoes: item.observacoes || "Recebido em lote pelo PCP." })) }))).then(() => { toast.success("Recebimento em lote registrado."); data.load(); }).catch((err) => toast.error(apiDetail(err, "Nao foi possivel receber em lote.")));
  }

  return (
    <div className="space-y-4">
      <Header title="Insumos por Pedido" subtitle="Matriz de checklist e alocacao fisica de insumos do PCP" />
      <div className="flex w-full max-w-3xl overflow-x-auto rounded-lg bg-muted p-1"><button className={`flex-1 rounded-md px-5 py-2 font-black ${tab === "mrp" ? "bg-primary text-primary-foreground shadow" : "text-muted-foreground"}`} onClick={() => setTab("mrp")}><FileSpreadsheet className="mr-2 inline h-4 w-4" />MRP - Necessidade de Materiais</button><button className={`flex-1 rounded-md px-5 py-2 font-black ${tab === "matriz" ? "bg-primary text-primary-foreground shadow" : "text-muted-foreground"}`} onClick={() => setTab("matriz")}><ClipboardList className="mr-2 inline h-4 w-4" />Visao Geral (Matriz)</button><button className={`flex-1 rounded-md px-5 py-2 font-black ${tab === "detalhes" ? "bg-primary text-primary-foreground shadow" : "text-muted-foreground"}`} onClick={() => setTab("detalhes")}><Search className="mr-2 inline h-4 w-4" />Detalhes do Pedido</button></div>
      {tab === "mrp" && <><div className="grid gap-3 md:grid-cols-3"><Stat value={fmt(actionOrders.length)} label="Compras atrasadas" tone="red" /><Stat value={fmt(actionOrders.reduce((sum, order) => sum + (order.checklist_insumos || []).filter((item) => item.ativo !== false).length, 0))} label="Materiais com acao" /><Stat value={fmt(rows.reduce((sum, order) => sum + (order.checklist_insumos || []).length, 0))} label="Materiais no plano" /></div><CardBox><CardContent className="space-y-3 p-4">{actionOrders.map((order) => <div key={order.id} className="rounded-lg border-l-4 border-l-red-500 bg-muted/30 p-4"><div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between"><div><b>{order.numero_pedido || order.id} - {orderTitle(order)}</b><p className="text-sm text-muted-foreground">{(order.checklist_insumos || []).filter((item) => item.ativo !== false).length} material(is) pendente(s)</p></div><Button variant="outline" onClick={() => { setSelectedId(order.id); setTab("detalhes"); setPurchaseOpen(true); }}><ShoppingCart className="mr-2 h-4 w-4" />Solicitar Compra</Button></div></div>)}{!actionOrders.length && <p className="py-8 text-center text-sm text-muted-foreground">Nenhuma compra atrasada para os filtros atuais.</p>}</CardContent></CardBox></>}
      {tab === "matriz" && <><CardBox><CardContent className="flex flex-col gap-3 p-4 md:flex-row md:items-center md:justify-between"><SearchInput value={q} setValue={setQ} placeholder="Filtrar por ID ou Produto..." /><Button onClick={receiveAll}><PackageCheck className="mr-2 h-4 w-4" />Recebimento em Lote</Button></CardContent></CardBox><CardBox className="overflow-hidden"><div className="overflow-x-auto"><table className="w-full min-w-[1000px] text-sm"><thead className="bg-muted text-xs uppercase text-muted-foreground"><tr><th className="p-3 text-left">Produto / SKU</th>{MATRIX_COLUMNS.map(([label]) => <th className="p-3 text-center" key={label}>{label}</th>)}</tr></thead><tbody>{rows.map((order) => <tr key={order.id} className="border-b"><td className="p-3 font-black">Pedido #{order.numero_pedido || order.id}<p className="text-xs text-muted-foreground">{customerName(order)} - {(order.items || []).length} item(ns)</p></td>{MATRIX_COLUMNS.map(([label, needles]) => <td key={label} className={`p-3 text-center font-black ${label === "OK" ? "bg-emerald-50 dark:bg-emerald-950/20" : ""}`}>{label === "OK" ? (orderOk(order) ? "✓" : "?") : checklistMark(checklistFor(order, needles))}</td>)}</tr>)}</tbody></table></div></CardBox></>}
      {tab === "detalhes" && selected && <><CardBox><CardContent className="grid gap-3 p-4 md:grid-cols-[1fr_auto_auto_auto]"><Select value={selected.id} onValueChange={setSelectedId}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent>{rows.map((order) => <SelectItem key={order.id} value={order.id}>#{order.numero_pedido || order.id} - {orderTitle(order)}</SelectItem>)}</SelectContent></Select><Button onClick={() => updateChecklist(selected, (items) => items.length ? items : MATRIX_COLUMNS.slice(0, 12).map(([label]) => ({ categoria: label, status: "pendente", ativo: true })), "BOM gerado para o pedido.")}>Gerar do BOM</Button><Button variant="outline" onClick={() => setPurchaseOpen(true)} disabled={!pendingInsumos.length}><ShoppingCart className="mr-2 h-4 w-4" />Solicitar Compra</Button><Button className="bg-emerald-600 text-white hover:bg-emerald-700" onClick={() => { if (newInsumo.trim()) updateChecklist(selected, (items) => [...items, { categoria: newInsumo.trim(), status: "pendente", ativo: true }], "Insumo adicionado."); setNewInsumo(""); }}>Novo Insumo</Button></CardContent></CardBox><CardBox><CardContent className="flex flex-col gap-3 p-4 md:flex-row md:items-center"><Badge variant="secondary">#{selected.numero_pedido || selected.id}</Badge><b className="flex-1">{orderTitle(selected)}</b><Badge className={orderOk(selected) ? "bg-emerald-100 text-emerald-700" : "bg-red-100 text-red-700"}>{orderOk(selected) ? "OK" : "Pendente"}</Badge><Button variant="outline" onClick={() => window.open(`/orders/${selected.id}`, "_blank")}>Ver pedido</Button></CardContent></CardBox><div className="grid gap-3 md:grid-cols-4"><Stat value={fmt((selected.checklist_insumos || []).length)} label="Insumos" /><Stat value={fmt((selected.checklist_insumos || []).filter((item) => ["recebido", "confirmado", "ok", "disponivel"].includes(norm(item.status))).length)} label="Recebidos" tone="green" /><Stat value={fmt((selected.checklist_insumos || []).filter((item) => norm(item.status) === "parcial").length)} label="Parciais" tone="amber" /><Stat value={fmt((selected.checklist_insumos || []).filter((item) => item.ativo !== false && !["recebido", "confirmado", "ok", "disponivel"].includes(norm(item.status))).length)} label="Pendentes" tone="red" /></div><Input value={newInsumo} onChange={(event) => setNewInsumo(event.target.value)} placeholder="Nome do novo insumo..." /><CardBox className="overflow-hidden"><CardHeader><CardTitle>{(selected.checklist_insumos || []).length} insumos cadastrados</CardTitle></CardHeader><div className="divide-y">{(selected.checklist_insumos || []).map((item, index) => <div key={`${item.categoria}-${index}`} className="grid gap-3 p-4 md:grid-cols-[1fr_110px_120px_44px] md:items-center"><div><b>{item.categoria || item.nome || `Insumo ${index + 1}`}</b><p className="text-xs text-muted-foreground">{item.observacoes || "Sem observacao"}</p></div><Badge className={["recebido", "confirmado", "ok", "disponivel"].includes(norm(item.status)) ? "bg-emerald-100 text-emerald-700" : "bg-red-100 text-red-700"}>{item.status || "pendente"}</Badge><Button size="sm" variant="outline" onClick={() => updateChecklist(selected, (items) => items.map((row, idx) => idx === index ? { ...row, status: "recebido" } : row), "Insumo recebido.")}>Receber</Button><Button size="icon" variant="ghost" onClick={() => updateChecklist(selected, (items) => items.filter((_, idx) => idx !== index), "Insumo removido.")}><Trash2 className="h-4 w-4 text-destructive" /></Button></div>)}{!(selected.checklist_insumos || []).length && <p className="p-8 text-center text-sm text-muted-foreground">Nenhum insumo fisico cadastrado para este pedido.</p>}</div></CardBox></>}
      <SolicitarCompraDialog open={purchaseOpen} onClose={() => setPurchaseOpen(false)} order={selected} onDone={data.load} />
    </div>
  );
}

function shortageQty(item) {
  const needed = Number(item.necessario ?? item.necessidade ?? item.quantidade_necessaria ?? item.qtd_necessaria ?? item.quantidade ?? item.qtd ?? 1);
  const available = Number(item.disponivel ?? item.saldo_disponivel ?? item.estoque_disponivel ?? item.saldo ?? 0);
  const explicit = Number(item.falta ?? item.qtd_faltante ?? item.quantidade_faltante ?? 0);
  const missing = explicit > 0 ? explicit : needed - available;
  return Math.max(missing, 1);
}

function materialNeedName(item) {
  return safeText(item.material_nome || item.item_descricao || item.descricao || item.categoria || item.nome, "Insumo");
}

function materialNeedCode(item) {
  return safeText(item.material_codigo || item.codigo_interno || item.codigo || item.sku || item.item_codigo, "");
}

function SolicitarCompraDialog({ open, onClose, order, onDone }) {
  const [comprasItens, setComprasItens] = useState([]);
  const [rows, setRows] = useState([]);
  const [justificativa, setJustificativa] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open || !order) return;
    const pending = (order.checklist_insumos || [])
      .filter((item) => item.ativo !== false && !["recebido", "confirmado", "ok", "disponivel"].includes(norm(item.status)))
      .map((item, index) => ({
        key: `${materialNeedName(item)}-${index}`,
        selected: true,
        source: item,
        nome: materialNeedName(item),
        codigo: materialNeedCode(item),
        quantidade: shortageQty(item),
        aviso: !materialNeedCode(item) ? "Insumo sem material vinculado" : Number(item.saldo || item.disponivel || 0) < 0 ? "saldo negativo" : "",
      }));
    setRows(pending);
    setJustificativa(`Necessidade apurada na Matriz de Insumos do pedido #${order.numero_pedido || order.id}.`);
    api.get("/compras/itens", { params: { limit: 500 } })
      .then((res) => setComprasItens(res.data?.itens || []))
      .catch(() => setComprasItens([]));
  }, [open, order]);

  const update = (key, patch) => setRows((current) => current.map((row) => row.key === key ? { ...row, ...patch } : row));
  const findMaterial = (row) => comprasItens.find((item) => {
    const code = norm(row.codigo);
    const name = norm(row.nome);
    return (code && norm(item.codigo_interno) === code) || norm(`${item.codigo_interno} ${item.descricao}`).includes(name);
  });
  const ensureMaterial = async (row) => {
    const existing = findMaterial(row);
    if (existing?.id) return existing;
    const codigo = (row.codigo || `MRP-${String(row.nome).replace(/\W+/g, "-").slice(0, 24)}`).slice(0, 48);
    try {
      const { data } = await api.post("/compras/itens", {
        codigo_interno: codigo,
        descricao: row.nome,
        categoria: "embalagem",
        sub_categoria: "MRP",
        unidade_compra: "un",
        fator_conversao_producao: 1,
        estoque_seguranca: 0,
        lead_time_dias: 0,
        requer_homologacao_cq: false,
        fornecedores_homologados: [],
      });
      return data;
    } catch (err) {
      if (err?.response?.status === 409) {
        const res = await api.get("/compras/itens", { params: { q: codigo, limit: 20 } });
        const found = (res.data?.itens || [])[0];
        if (found?.id) return found;
      }
      throw err;
    }
  };

  const send = async () => {
    const selected = rows.filter((row) => row.selected && Number(row.quantidade) > 0);
    if (!selected.length) return toast.error("Selecione pelo menos um insumo com quantidade.");
    setSaving(true);
    try {
      await Promise.all(selected.map(async (row) => {
        const material = await ensureMaterial(row);
        return api.post("/compras/demandas", {
          item_id: material.id,
          quantidade: Number(row.quantidade),
          motivo: "mrp",
          observacoes: `${justificativa} Origem: pedido #${order.numero_pedido || order.id}; insumo ${row.nome}; conta necessario - disponivel.`,
          fornecedor_selecionado_id: null,
        });
      }));
      toast.success("Solicitação enviada para Compras.");
      onDone?.();
      onClose();
    } catch (err) {
      toast.error(apiDetail(err, "Nao foi possivel enviar para Compras."));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(value) => !value && onClose()}>
      <DialogContent className="max-h-[86vh] max-w-4xl overflow-hidden">
        <DialogHeader><DialogTitle>Solicitar Compra - Matriz de Insumos</DialogTitle></DialogHeader>
        <div className="max-h-[60vh] space-y-3 overflow-y-auto">
          <div className="rounded-md border-l-4 border-l-amber-500 bg-amber-50 p-3 text-sm text-amber-900 dark:bg-amber-950/30 dark:text-amber-100">
            Confira item a item. A quantidade vem da falta apurada na matriz: necessario menos disponivel. Itens recebidos ou cobertos pelo estoque ficam fora desta lista.
          </div>
          <div className="overflow-x-auto rounded-lg border">
            <table className="w-full min-w-[820px] text-sm">
              <thead className="bg-muted text-xs uppercase text-muted-foreground"><tr><th className="p-3" /><th className="p-3 text-left">Insumo</th><th className="p-3 text-left">Codigo</th><th className="p-3 text-left">Quantidade</th><th className="p-3 text-left">Aviso</th></tr></thead>
              <tbody>
                {rows.map((row) => <tr key={row.key} className="border-t"><td className="p-3"><input type="checkbox" checked={row.selected} onChange={(event) => update(row.key, { selected: event.target.checked })} /></td><td className="p-3 font-bold">{row.nome}</td><td className="p-3"><Input value={row.codigo} onChange={(event) => update(row.key, { codigo: event.target.value })} placeholder="codigo do material" /></td><td className="p-3"><Input type="number" min="0.001" step="0.001" value={row.quantidade} onChange={(event) => update(row.key, { quantidade: event.target.value })} /></td><td className="p-3 text-amber-700">{row.aviso || (findMaterial(row) ? "vinculado" : "novo cadastro em Compras")}</td></tr>)}
                {!rows.length && <tr><td colSpan={5} className="p-8 text-center text-muted-foreground">Nenhum insumo pendente para solicitar compra.</td></tr>}
              </tbody>
            </table>
          </div>
          <Field label="Justificativa">
            <Textarea value={justificativa} onChange={(event) => setJustificativa(event.target.value)} />
          </Field>
        </div>
        <DialogFooter><Button variant="outline" onClick={onClose}>Cancelar</Button><Button onClick={send} disabled={saving || !rows.some((row) => row.selected)}>{saving && <RefreshCw className="mr-2 h-4 w-4 animate-spin" />}Enviar para Compras</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function HistoryModule() {
  const data = usePcpData();
  const [tab, setTab] = useState("registro");
  const [q, setQ] = useState("");
  const [line, setLine] = useState("all");
  const [kind, setKind] = useState("all");
  const rows = (data.historico.rows || []).filter((row) => `${row.data} ${row.hora} ${row.produto} ${row.lote} ${row.pedido_numero} ${row.linha_nome}`.toLowerCase().includes(q.toLowerCase()) && (line === "all" || row.linha_nome === line) && (kind === "all" || row.tipo === kind));
  const byPedido = Object.values(rows.reduce((acc, row) => { const key = row.pedido_numero || "Sem pedido"; acc[key] ||= { pedido: key, qtd: 0, registros: 0 }; acc[key].qtd += Number(row.qtd || 0); acc[key].registros += 1; return acc; }, {}));
  const byOp = Object.values(rows.reduce((acc, row) => { const key = row.op_numero || row.lote || "Sem OP"; acc[key] ||= { op: key, qtd: 0, registros: 0 }; acc[key].qtd += Number(row.qtd || 0); acc[key].registros += 1; return acc; }, {}));
  const motivos = Object.values(rows.reduce((acc, row) => { const key = row.paradas || row.motivo || "-"; acc[key] ||= { motivo: key, qtd: 0 }; acc[key].qtd += 1; return acc; }, {}));
  function exportCsv() {
    csvDownload("historico_pcp.csv", [["Data", "Hora", "Produto", "Linha", "Qtd", "Lote", "Pedido", "Colab", "Paradas", "Turno"], ...rows.map((row) => [row.data, row.hora, row.produto, row.linha_nome, row.qtd, row.lote || row.op_numero, row.pedido_numero, row.colab, row.paradas, row.turno])]);
  }
  return (
    <div className="space-y-4">
      <Header title="Historico de Producao" subtitle="Todos os apontamentos - por data e pedido" />
      <div className="flex flex-wrap gap-2"><Button variant="outline" onClick={exportCsv}><Download className="mr-2 h-4 w-4" />Exportar CSV</Button><Button className="bg-amber-600 text-white hover:bg-amber-700" onClick={() => data.load()}><RefreshCw className="mr-2 h-4 w-4" />Reconciliar Pedidos</Button></div>
      <CardBox><CardContent className="grid gap-2 p-4 md:grid-cols-[170px_170px_100px_1fr_140px_150px]"><Input type="date" value={data.historyRange.inicio} onChange={(event) => data.setHistoryRange({ ...data.historyRange, inicio: event.target.value })} /><Input type="date" value={data.historyRange.fim} onChange={(event) => data.setHistoryRange({ ...data.historyRange, fim: event.target.value })} /><Button className="bg-emerald-600 text-white hover:bg-emerald-700" onClick={() => data.load()}>Carregar</Button><SearchInput value={q} setValue={setQ} placeholder="Produto, lote, pedido, linha..." /><Select value={line} onValueChange={setLine}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="all">Todas linha</SelectItem>{data.linhas.map((linha) => <SelectItem key={linha.id} value={linha.nome}>{linha.nome}</SelectItem>)}</SelectContent></Select><Select value={kind} onValueChange={setKind}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="all">Todos registros</SelectItem><SelectItem value="apontamento">Apontamento</SelectItem><SelectItem value="slot">Slot</SelectItem><SelectItem value="fechamento">Fechamento</SelectItem></SelectContent></Select></CardContent></CardBox>
      <div className="grid gap-3 md:grid-cols-5"><Stat value={fmt(rows.length)} label="Registros" tone="green" /><Stat value={fmt(data.historico.kpis?.total_produzido || rows.reduce((sum, row) => sum + Number(row.qtd || 0), 0))} label="Total produzido" tone="green" /><Stat value={fmt(rows.filter((row) => row.pedido_numero).length)} label="Com pedido" /><Stat value={fmt(new Set(rows.map((row) => row.data)).size)} label="Dias" /><Stat value={fmt(data.historico.kpis?.pedidos_unicos || new Set(rows.map((row) => row.pedido_numero).filter(Boolean)).size)} label="Pedidos unicos" tone="amber" /></div>
      <CardBox className="overflow-hidden"><div className="flex gap-1 overflow-x-auto border-b p-3">{["registro", "pedido", "op", "motivos"].map((value) => <Button key={value} variant={tab === value ? "default" : "ghost"} onClick={() => setTab(value)}>{value === "registro" ? "Por Registro" : value === "pedido" ? "Por Pedido" : value === "op" ? "Por OP" : "Motivos Recorrentes"}</Button>)}</div><div className="overflow-x-auto">{tab === "registro" && <HistoryTable rows={rows} />}{tab === "pedido" && <SmallAggregate headers={["Pedido", "Registros", "Qtd."]} rows={byPedido.map((row) => [row.pedido, row.registros, fmt(row.qtd)])} />}{tab === "op" && <SmallAggregate headers={["OP", "Registros", "Qtd."]} rows={byOp.map((row) => [row.op, row.registros, fmt(row.qtd)])} />}{tab === "motivos" && <SmallAggregate headers={["Motivo", "Ocorrencias"]} rows={motivos.map((row) => [row.motivo, row.qtd])} />}</div></CardBox>
    </div>
  );
}

function HistoryTable({ rows }) {
  return <table className="w-full min-w-[980px] text-sm"><thead className="bg-muted text-xs uppercase text-muted-foreground"><tr>{["Data", "Hora", "Produto", "Linha", "Qtd.", "Lote", "Pedido", "Colab.", "Paradas", "Turno", "Acoes"].map((h) => <th className="p-3 text-left" key={h}>{h}</th>)}</tr></thead><tbody>{rows.map((row, i) => <tr className="border-b" key={`${row.id || i}`}><td className="p-3">{row.data || "-"}</td><td className="p-3">{row.hora || "-"}</td><td className="p-3">{row.produto || "-"}</td><td className="p-3">{row.linha_nome || "-"}</td><td className="p-3">{fmt(row.qtd)}</td><td className="p-3">{row.lote || row.op_numero || "-"}</td><td className="p-3">{row.pedido_numero || "-"}</td><td className="p-3">{row.colab || "-"}</td><td className="p-3">{row.paradas || "-"}</td><td className="p-3">{row.turno || "-"}</td><td className="p-3"><div className="flex gap-1"><Button size="sm" variant="outline" onClick={() => toast.info("Edicao deve ser feita no detalhe da OP para preservar auditoria.")}>Editar</Button><Button size="sm" variant="outline" onClick={() => toast.info("Exclusao direta bloqueada por auditoria; use ajuste no detalhe da OP.")}>Excluir</Button></div></td></tr>)}{!rows.length && <tr><td colSpan={11} className="p-8 text-center text-muted-foreground">Selecione o periodo e clique em Carregar.</td></tr>}</tbody></table>;
}

function SmallAggregate({ headers, rows }) {
  return <table className="w-full min-w-[620px] text-sm"><thead className="bg-muted text-xs uppercase text-muted-foreground"><tr>{headers.map((header) => <th key={header} className="p-3 text-left">{header}</th>)}</tr></thead><tbody>{rows.map((row, index) => <tr key={index} className="border-b">{row.map((cell, cellIndex) => <td key={cellIndex} className="p-3">{cell}</td>)}</tr>)}{!rows.length && <tr><td className="p-8 text-center text-muted-foreground" colSpan={headers.length}>Sem dados.</td></tr>}</tbody></table>;
}

function Field({ label, children, className = "" }) {
  return (
    <label className={`block space-y-1 ${className}`}>
      <Label className="text-xs font-black uppercase text-muted-foreground">{label}</Label>
      {children}
    </label>
  );
}

function RegistroModule() {
  const data = usePcpData();
  const navigate = useNavigate();
  const [openTurn, setOpenTurn] = useState(true);
  const [registroTab, setRegistroTab] = useState("horario");
  const [selectedOpId, setSelectedOpId] = useState("");
  const [workPosts, setWorkPosts] = useState([]);
  const [workPostForm, setWorkPostForm] = useState({ linha: "", posto: "", operador: "" });
  const [pointForm, setPointForm] = useState({ total: "", turno: "Padrao", observacoes: "", parada_tipo: "outro", parada_motivo: "", perda_item: "0", perda_tipo: "processo", perda_qtd: "", perda_unidade: "un", perda_motivo: "" });
  const [retroForm, setRetroForm] = useState({ data: ymd(new Date()), hora: "07:00", qtd: "", observacoes: "" });
  const [saving, setSaving] = useState(false);
  const lines = data.linhas.length ? data.linhas : [{ id: "linha-1", nome: "Linha 1" }, { id: "linha-2", nome: "Linha 2" }, { id: "linha-3", nome: "Linha 3" }];
  const activeOps = data.ops.filter((op) => ["aberta", "em_processo", "pausada"].includes(op.status));
  const selectedOp = activeOps.find((op) => op.id === selectedOpId) || activeOps[0];
  const selectedItems = selectedOp?.items || selectedOp?.materiais || selectedOp?.insumos || [];
  const byLine = lines.map((line) => ({ line, op: activeOps.find((op) => op.linha_id === line.id || op.linha_nome === line.nome) }));
  const recent = (data.historico.rows || []).slice(0, 10);
  const todayTotal = recent.reduce((sum, row) => sum + Number(row.qtd || 0), 0);
  const pointedTotal = producedQty(selectedOp);

  async function setStatus(op, status) {
    if (!op) return toast.info("Nenhuma OP alocada nesta linha.");
    try {
      await api.put(`/ops/${op.id}`, { status });
      toast.success(status === "em_processo" ? "Producao retomada." : "Status atualizado.");
      data.load();
    } catch (err) {
      toast.error(apiDetail(err, "Nao foi possivel atualizar OP."));
    }
  }

  async function apontarTotal({ retro = false } = {}) {
    if (!selectedOp) return toast.info("Selecione uma OP.");
    const qtd = Number(retro ? retroForm.qtd : pointForm.total);
    if (qtd <= 0) return toast.error("Informe a quantidade total produzida.");
    setSaving(true);
    try {
      if (selectedOp.status === "aberta") await api.put(`/ops/${selectedOp.id}`, { status: "em_processo" });
      const payload = {
        item_idx: 0,
        qtd_produzida: qtd,
        turno: pointForm.turno,
        setor: "apontamento_total",
        observacoes: retro
          ? [`Retroativo ${retroForm.data} ${retroForm.hora}`, retroForm.observacoes].filter(Boolean).join(" - ")
          : pointForm.observacoes,
      };
      if (retro) payload.horario = `${retroForm.data}T${retroForm.hora || "00:00"}:00`;
      await api.post(`/ops/${selectedOp.id}/apontar`, payload);
      toast.success(retro ? "Registro atrasado lancado." : "Apontamento por total registrado.");
      setPointForm((form) => ({ ...form, total: "", observacoes: "" }));
      setRetroForm({ data: ymd(new Date()), hora: "07:00", qtd: "", observacoes: "" });
      data.load();
    } catch (err) {
      toast.error(apiDetail(err, "Nao foi possivel apontar a producao."));
    } finally {
      setSaving(false);
    }
  }

  async function registrarParada() {
    if (!selectedOp) return toast.info("Selecione uma OP.");
    if (!pointForm.parada_motivo.trim()) return toast.error("Informe o motivo da parada.");
    setSaving(true);
    try {
      await api.post(`/ops/${selectedOp.id}/pausar`, { tipo: pointForm.parada_tipo, motivo: pointForm.parada_motivo });
      toast.success("Parada registrada.");
      setPointForm((form) => ({ ...form, parada_motivo: "" }));
      data.load();
    } catch (err) {
      toast.error(apiDetail(err, "Nao foi possivel registrar parada."));
    } finally {
      setSaving(false);
    }
  }

  async function registrarPerda() {
    if (!selectedOp) return toast.info("Selecione uma OP.");
    if (Number(pointForm.perda_qtd) <= 0) return toast.error("Informe a quantidade da perda.");
    setSaving(true);
    try {
      await api.post(`/ops/${selectedOp.id}/perda`, {
        item_idx: Number(pointForm.perda_item || 0),
        tipo: pointForm.perda_tipo,
        quantidade: Number(pointForm.perda_qtd),
        unidade: pointForm.perda_unidade,
        motivo: pointForm.perda_motivo,
      });
      toast.success("Perda registrada e descontada.");
      setPointForm((form) => ({ ...form, perda_qtd: "", perda_motivo: "" }));
      data.load();
    } catch (err) {
      toast.error(apiDetail(err, "Nao foi possivel registrar perda."));
    } finally {
      setSaving(false);
    }
  }

  async function fecharLote() {
    if (!selectedOp) return toast.info("Selecione uma OP.");
    const progress = plannedQty(selectedOp) ? Math.round((producedQty(selectedOp) / plannedQty(selectedOp)) * 100) : 0;
    if (progress < 100 && !window.confirm(`A OP esta com ${progress}% produzido. Fechar lote mesmo assim?`)) return;
    await setStatus(selectedOp, "aguardando_confirmacao_pcp");
  }

  function addWorkPost() {
    const linha = workPostForm.linha || lines[0]?.nome || "Linha";
    const posto = workPostForm.posto || "Posto aberto";
    setWorkPosts((posts) => [...posts, { ...workPostForm, linha, posto, id: Date.now() }]);
    setWorkPostForm({ linha: "", posto: "", operador: "" });
    toast.success("Posto de trabalho aberto.");
  }

  function allocate(line) {
    navigate(`/pcp/emitir-op?linha=${encodeURIComponent(line.nome)}`);
  }

  return (
    <div className="mx-auto max-w-[760px] space-y-4">
      <Header title="Registro de Producao" subtitle={new Date().toLocaleDateString("pt-BR", { weekday: "long", day: "2-digit", month: "long", year: "numeric" })} />
      <CardBox className="border-l-4 border-l-primary">
        <CardContent className="flex flex-col gap-3 p-5 md:flex-row md:items-center md:justify-between">
          <div><p className="text-xs text-muted-foreground">Turno atual</p><b>{openTurn ? "Padrao - inicio 07:00" : "Turno encerrado"}</b></div>
          <div className="flex gap-2"><Button variant="outline" onClick={() => setOpenTurn(true)}>Iniciar turno</Button><Button onClick={() => setOpenTurn(false)}>Encerrar turno</Button></div>
        </CardContent>
      </CardBox>
      <CardBox className="border-l-4 border-l-primary">
        <CardContent className="space-y-4 p-5">
          <div className="grid gap-2 md:grid-cols-3">
            {[
              ["horario", "Apontamento Horario"],
              ["total", "Apontamento por Total"],
              ["fechar", "Fechar Lote (OP)"],
            ].map(([value, label]) => <Button key={value} variant={registroTab === value ? "default" : "outline"} onClick={() => setRegistroTab(value)}>{label}</Button>)}
          </div>
          <div className="rounded-md border-l-4 border-l-amber-500 bg-amber-50 p-3 text-sm text-amber-800 dark:bg-amber-950/20 dark:text-amber-200">
            A rotina da Kuryos e abrir a OP quando a linha comeca, encerrar quando para e informar apenas o total produzido. A aba horaria existe para excecao; a rotina principal e Apontamento por Total.
          </div>
          <div className="grid gap-3 md:grid-cols-[1fr_140px]">
            <Select value={selectedOp?.id || ""} onValueChange={setSelectedOpId}>
              <SelectTrigger><SelectValue placeholder="Selecione a OP em producao" /></SelectTrigger>
              <SelectContent>{activeOps.map((op) => <SelectItem key={op.id} value={op.id}>{op.numero_op} - {productText(op)}</SelectItem>)}</SelectContent>
            </Select>
            <Button variant="outline" onClick={() => selectedOp ? navigate(`/ops/${selectedOp.id}`) : toast.info("Selecione uma OP.")}>Ver OP</Button>
          </div>
          {registroTab === "horario" && (
            <div className="space-y-3 rounded-lg border p-4">
              <div><b>Apontamento Horario</b><p className="text-sm text-muted-foreground">Nao e a rotina normal. Use somente para lancamento hora a hora ou ajuste orientado pelo PCP.</p></div>
              <div className="grid gap-3 md:grid-cols-3"><Input type="number" placeholder="Qtd. da hora" value={retroForm.qtd} onChange={(event) => setRetroForm({ ...retroForm, qtd: event.target.value })} /><Input type="time" value={retroForm.hora} onChange={(event) => setRetroForm({ ...retroForm, hora: event.target.value })} /><Button disabled={saving} onClick={() => apontarTotal({ retro: true })}>Lancar registro</Button></div>
            </div>
          )}
          {registroTab === "total" && (
            <div className="space-y-4 rounded-lg border p-4">
              <div className="grid gap-2 md:grid-cols-3"><Button onClick={() => setStatus(selectedOp, "em_processo")} disabled={!openTurn || saving}>Abrir OP / Retomar</Button><Button variant="outline" onClick={registrarParada} disabled={!openTurn || saving}>Adicionar parada</Button><Button variant="outline" onClick={registrarPerda} disabled={!openTurn || saving}>Adicionar perda</Button></div>
              <div className="grid gap-3 md:grid-cols-[1fr_150px]"><Input type="number" min="0" placeholder="Quantidade total produzida ate agora" value={pointForm.total} onChange={(event) => setPointForm({ ...pointForm, total: event.target.value })} /><Button className="bg-emerald-600 text-white hover:bg-emerald-700" disabled={!openTurn || saving} onClick={() => apontarTotal()}>Encerrar OP</Button></div>
              <Textarea placeholder="Observacoes do apontamento" value={pointForm.observacoes} onChange={(event) => setPointForm({ ...pointForm, observacoes: event.target.value })} />
              <div className="grid gap-3 md:grid-cols-2">
                <div className="rounded-md bg-muted p-3"><Label className="text-xs font-black uppercase text-muted-foreground">Parada</Label><div className="mt-2 grid gap-2 md:grid-cols-[150px_1fr]"><Select value={pointForm.parada_tipo} onValueChange={(value) => setPointForm({ ...pointForm, parada_tipo: value })}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent>{DEFAULT_STOP_REASONS.map((reason) => <SelectItem key={reason} value={reason}>{reason}</SelectItem>)}</SelectContent></Select><Input placeholder="Motivo e duracao" value={pointForm.parada_motivo} onChange={(event) => setPointForm({ ...pointForm, parada_motivo: event.target.value })} /></div></div>
                <div className="rounded-md bg-muted p-3"><Label className="text-xs font-black uppercase text-muted-foreground">Perda</Label><div className="mt-2 grid gap-2 md:grid-cols-2"><Select value={pointForm.perda_item} onValueChange={(value) => setPointForm({ ...pointForm, perda_item: value })}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent>{(selectedItems.length ? selectedItems : [{ nome: "Material da OP" }]).map((item, index) => <SelectItem key={index} value={String(index)}>{item.nome || item.descricao || item.codigo || `Item ${index + 1}`}</SelectItem>)}</SelectContent></Select><Input type="number" placeholder="Qtd. perda" value={pointForm.perda_qtd} onChange={(event) => setPointForm({ ...pointForm, perda_qtd: event.target.value })} /><Input placeholder="Un." value={pointForm.perda_unidade} onChange={(event) => setPointForm({ ...pointForm, perda_unidade: event.target.value })} /><Input placeholder="Motivo" value={pointForm.perda_motivo} onChange={(event) => setPointForm({ ...pointForm, perda_motivo: event.target.value })} /></div></div>
              </div>
            </div>
          )}
          {registroTab === "fechar" && (
            <div className="space-y-3 rounded-lg border p-4">
              <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between"><div><b>{selectedOp?.numero_op || "Nenhuma OP selecionada"}</b><p className="text-sm text-muted-foreground">Total apontado: {fmt(pointedTotal)} / {fmt(plannedQty(selectedOp))} un.</p></div><Button className="bg-emerald-600 text-white hover:bg-emerald-700" disabled={saving || !selectedOp} onClick={fecharLote}>Fechar Lote (OP)</Button></div>
              <div className="grid gap-3 md:grid-cols-[160px_1fr_160px]"><Input type="date" value={retroForm.data} onChange={(event) => setRetroForm({ ...retroForm, data: event.target.value })} /><Input placeholder="Observacao final / perda final do lote" value={retroForm.observacoes} onChange={(event) => setRetroForm({ ...retroForm, observacoes: event.target.value })} /><Button variant="outline" onClick={() => setRegistroTab("total")}>Voltar ao total</Button></div>
            </div>
          )}
          <details className="rounded-lg border p-3">
            <summary className="cursor-pointer text-sm font-bold">Lancar registro atrasado / trocar OP desta linha</summary>
            <div className="mt-3 grid gap-2 md:grid-cols-[150px_120px_1fr_140px]"><Input type="date" value={retroForm.data} onChange={(event) => setRetroForm({ ...retroForm, data: event.target.value })} /><Input type="time" value={retroForm.hora} onChange={(event) => setRetroForm({ ...retroForm, hora: event.target.value })} /><Input placeholder="Quantidade total retroativa" value={retroForm.qtd} onChange={(event) => setRetroForm({ ...retroForm, qtd: event.target.value })} /><Button variant="outline" disabled={saving} onClick={() => apontarTotal({ retro: true })}>Lancar atrasado</Button></div>
          </details>
        </CardContent>
      </CardBox>
      <div>
        <h2 className="mb-2 text-xs font-black uppercase text-muted-foreground">Linhas de Producao</h2>
        <div className="grid gap-3 md:grid-cols-2">
          {byLine.map(({ line, op }) => <CardBox key={line.id} className={op?.status === "pausada" ? "border-red-200 bg-red-50 dark:border-red-900 dark:bg-red-950/20" : ""}><CardContent className="space-y-3 p-4"><div className="flex items-center justify-between gap-2"><b>{line.nome}</b><Badge variant="secondary">Linha</Badge></div>{op?.status === "pausada" && <div className="rounded-md bg-red-100 p-2 text-xs font-bold text-red-700 dark:bg-red-950 dark:text-red-300">Parada: aguardando retomada</div>}{op ? <div className="rounded-md border border-dashed p-3 text-sm"><b>{op.numero_op}</b><p className="text-xs text-muted-foreground">{productText(op)}</p><p className="mt-1 text-xs text-muted-foreground">{fmt(producedQty(op))} / {fmt(plannedQty(op))} un.</p></div> : <div className="rounded-md border border-dashed p-3 text-center text-sm text-muted-foreground">Nenhuma OP alocada</div>}<div className="grid gap-2"><Button variant="outline" className="bg-emerald-50 text-emerald-700 hover:bg-emerald-100 dark:bg-emerald-950/30 dark:text-emerald-300" onClick={() => setStatus(op, "em_processo")}>Retomar Producao</Button><Button onClick={() => allocate(line)}>Alocar OP</Button></div></CardContent></CardBox>)}
        </div>
      </div>
      <div>
        <h2 className="mb-2 text-xs font-black uppercase text-muted-foreground">Rotulagem</h2>
        <div className="grid gap-3 md:grid-cols-2">{["Rotulagem 01", "Rotulagem 02"].map((label) => <CardBox key={label}><CardContent className="space-y-3 p-4"><div className="flex items-center justify-between"><b>{label}</b><Badge className="bg-emerald-100 text-emerald-700">Rotulagem</Badge></div><div className="rounded-md border border-dashed p-3 text-center text-sm text-muted-foreground">Nenhuma OP alocada</div><Button className="w-full" onClick={() => navigate("/pcp/controle-ops")}>Alocar OP</Button></CardContent></CardBox>)}</div>
      </div>
      <CardBox><CardContent className="space-y-3 p-4"><div className="flex items-center justify-between"><h2 className="text-xs font-black uppercase text-muted-foreground">Postos de trabalho abertos neste turno</h2><Button size="sm" variant="outline" onClick={addWorkPost}>Abrir posto de trabalho</Button></div><div className="grid gap-2 md:grid-cols-3"><Select value={workPostForm.linha || lines[0]?.nome || "Linha"} onValueChange={(value) => setWorkPostForm({ ...workPostForm, linha: value })}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent>{lines.map((line) => <SelectItem key={line.id} value={line.nome}>{line.nome}</SelectItem>)}</SelectContent></Select><Input placeholder="Posto / area" value={workPostForm.posto} onChange={(event) => setWorkPostForm({ ...workPostForm, posto: event.target.value })} /><Input placeholder="Operador" value={workPostForm.operador} onChange={(event) => setWorkPostForm({ ...workPostForm, operador: event.target.value })} /></div>{workPosts.length ? <div className="divide-y rounded-md border">{workPosts.map((post) => <div key={post.id} className="grid gap-2 p-3 text-sm md:grid-cols-[1fr_1fr_1fr_40px]"><b>{post.linha}</b><span>{post.posto}</span><span>{post.operador || "Sem operador"}</span><Button size="icon" variant="ghost" onClick={() => setWorkPosts((posts) => posts.filter((item) => item.id !== post.id))}><Trash2 className="h-4 w-4" /></Button></div>)}</div> : <div className="rounded-md bg-amber-50 p-3 text-sm text-amber-700 dark:bg-amber-950/20 dark:text-amber-300">Nenhum posto aberto neste turno.</div>}</CardContent></CardBox>
      <div className="grid gap-3 md:grid-cols-4"><Stat value={fmt(todayTotal)} label="Linhas Hoje" /><Stat value="0" label="Rotulagem Hoje" /><Stat value="0" label="Postos Hoje" /><Stat value={fmt(recent.length)} label="Registros no Dia" /></div>
      <CardBox className="border-l-4 border-l-primary"><CardHeader><CardTitle className="text-sm uppercase text-muted-foreground">Ultimos Registros de Hoje</CardTitle></CardHeader><CardContent className="space-y-2">{recent.map((row, index) => <div key={`${row.id || index}`} className="grid gap-2 border-b py-2 text-sm md:grid-cols-[120px_1fr_80px]"><b className="text-primary">{row.hora || row.data || "-"}</b><span>{row.produto || row.op_numero || "Registro"}</span><b className="text-right">{fmt(row.qtd)}</b></div>)}{!recent.length && <p className="py-8 text-center text-sm text-muted-foreground">Nenhum registro hoje.</p>}</CardContent></CardBox>
    </div>
  );
}

export default function PCPLegacyClonePage({ mode }) {
  const content =
    mode === "controle" ? <ControlOpsModule /> :
    mode === "emitir-op" ? <EmitOPModule /> :
    mode === "matriz" ? <MatrixModule /> :
    mode === "historico" ? <HistoryModule /> :
    mode === "registro" ? <RegistroModule /> :
    mode === "ajustes" ? <PlanningModule initial="config" /> :
    <PlanningModule initial="quantidades" />;

  return <div className="mx-auto max-w-[1280px] p-6">{content}</div>;
}
