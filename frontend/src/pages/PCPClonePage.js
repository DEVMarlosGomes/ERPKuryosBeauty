import { useCallback, useEffect, useMemo, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import api from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import {
  AlertTriangle, ArrowRight, CalendarDays, CheckCircle2, ClipboardList, Clock, Factory, FileSpreadsheet, Lock, Pencil, RefreshCw, Search, XCircle,
} from "lucide-react";
import { toast } from "sonner";

function toYMD(date) { return date.toISOString().slice(0, 10); }
function parseYMD(ymd) {
  const [y, m, d] = ymd.split("-").map(Number);
  return new Date(y, m - 1, d);
}
function addDays(ymd, days) {
  const d = parseYMD(ymd);
  d.setDate(d.getDate() + days);
  return toYMD(d);
}
function startOfWeek(ymd) {
  const d = parseYMD(ymd);
  const day = d.getDay();
  d.setDate(d.getDate() - (day === 0 ? 6 : day - 1));
  return toYMD(d);
}
function isoWeekKey(ymd) {
  const d = parseYMD(ymd);
  d.setHours(0, 0, 0, 0);
  d.setDate(d.getDate() + 3 - ((d.getDay() + 6) % 7));
  const week1 = new Date(d.getFullYear(), 0, 4);
  const week = 1 + Math.round(((d - week1) / 86400000 - 3 + ((week1.getDay() + 6) % 7)) / 7);
  return `${d.getFullYear()}-${String(week).padStart(2, "0")}`;
}
function fmt(n) { return Number(n || 0).toLocaleString("pt-BR"); }
function pct(produced, target) {
  return target > 0 ? Math.min(Math.round((produced / target) * 100), 100) : 0;
}
const WEEK_DAYS = [
  { key: "seg", label: "Segunda", short: "Seg" },
  { key: "ter", label: "Terca", short: "Ter" },
  { key: "qua", label: "Quarta", short: "Qua" },
  { key: "qui", label: "Quinta", short: "Qui" },
  { key: "sex", label: "Sexta", short: "Sex" },
  { key: "sab", label: "Sabado", short: "Sab" },
  { key: "dom", label: "Domingo", short: "Dom" },
];
function dateLabel(ymd) {
  try {
    return parseYMD(ymd).toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" });
  } catch {
    return ymd;
  }
}
function minutesBetween(start, end) {
  const [sh, sm] = String(start || "07:00").split(":").map(Number);
  const [eh, em] = String(end || "17:00").split(":").map(Number);
  return Math.max((eh * 60 + em) - (sh * 60 + sm), 0);
}
function slotProgress(slot) {
  return pct(Number(slot.qtd_produzida || 0), Number(slot.qtd_planejada || 0));
}

function Shell({ children }) {
  return (
    <div className="pcp-theme min-h-full bg-black text-white">
      <main className="mx-auto min-h-screen w-full max-w-[1440px] px-4 py-6 md:px-8 lg:px-9">{children}</main>
    </div>
  );
}

function DarkCard({ children, className = "" }) {
  return <section className={`rounded-2xl bg-[#1f1f22] p-5 ${className}`}>{children}</section>;
}

function Stat({ value, label }) {
  return (
    <div className="relative overflow-hidden rounded-xl bg-[#1f1f22] px-5 py-6 text-center">
      <span className="absolute inset-x-0 top-0 h-0.5 bg-[#6485f2]" />
      <p className="text-2xl font-black">{value || "-"}</p>
      <p className="mt-2 text-[11px] font-black uppercase tracking-wide text-zinc-500">{label}</p>
    </div>
  );
}

function usePcpData() {
  const [loading, setLoading] = useState(true);
  const [linhas, setLinhas] = useState([]);
  const [slots, setSlots] = useState([]);
  const [ops, setOps] = useState([]);
  const [orders, setOrders] = useState([]);
  const [skus, setSkus] = useState([]);
  const [catalog, setCatalog] = useState([]);
  const [historico, setHistorico] = useState({ rows: [], kpis: {} });
  const [day, setDay] = useState(() => toYMD(new Date()));

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const ini = startOfWeek(day);
      const fim = addDays(ini, 6);
      const safeGet = (url, config, fallback) => api.get(url, config).catch(() => ({ data: fallback }));
      const [linhasRes, slotsRes, opsRes, ordersRes, skusRes, catalogRes, histRes] = await Promise.all([
        safeGet("/pcp/linhas", undefined, []),
        safeGet("/pcp/programacao", { params: { data_inicio: ini, data_fim: fim } }, []),
        safeGet("/ops", undefined, []),
        safeGet("/orders", undefined, []),
        safeGet("/crm/skus", undefined, []),
        safeGet("/pd/catalog", undefined, []),
        safeGet("/pcp/historico", { params: { data_inicio: ini, data_fim: fim } }, { rows: [], kpis: {} }),
      ]);
      setLinhas(linhasRes.data || []);
      setSlots(slotsRes.data || []);
      setOps(opsRes.data || []);
      setOrders(ordersRes.data || []);
      setSkus(skusRes.data || []);
      setCatalog(catalogRes.data || []);
      setHistorico(histRes.data || { rows: [], kpis: {} });
    } catch {
      toast.error("Erro ao carregar dados do PCP");
    } finally {
      setLoading(false);
    }
  }, [day]);

  useEffect(() => { load(); }, [load]);
  return { loading, linhas, slots, ops, orders, skus, catalog, historico, day, setDay, load };
}

function PlanningPage({ data }) {
  const location = useLocation();
  const navigate = useNavigate();
  const tabParam = new URLSearchParams(location.search).get("tab");
  const initialTab = ["grade", "ops", "agenda", "config"].includes(tabParam) ? tabParam : "grade";
  const [tab, setTab] = useState(initialTab);
  const [search, setSearch] = useState("");
  const [schedulingId, setSchedulingId] = useState("");
  const weekStart = startOfWeek(data.day);
  const weekEnd = addDays(weekStart, 6);
  const [selectedDay, setSelectedDay] = useState(weekStart);
  const [editingSlot, setEditingSlot] = useState(null);
  const [savingSlot, setSavingSlot] = useState(false);
  const [calendarSaving, setCalendarSaving] = useState(false);
  const [calendarForm, setCalendarForm] = useState({
    data_inicio: weekStart,
    data_fim: weekEnd,
    linha_id: "all",
    dias: ["seg", "ter", "qua", "qui", "sex"],
    habilitado: true,
    hora_inicio: "07:00",
    hora_fim: "18:00",
    turnos: "1",
    observacoes: "",
  });
  const activeOps = data.ops.filter(op => ["aberta", "em_processo", "pausada", "aguardando_confirmacao_pcp"].includes(op.status));
  const activeLines = data.linhas.filter(linha => linha.status !== "inativa");
  const totalPlanejado = data.slots.reduce((s, slot) => s + Number(slot.qtd_planejada || 0), 0);
  const diasProgramados = new Set(data.slots.map(slot => slot.data || slot.data_inicio).filter(Boolean)).size;
  const weekDays = WEEK_DAYS.map((dayDef, index) => ({ ...dayDef, date: addDays(weekStart, index) }));
  const scheduledOpIds = new Set(data.slots.filter((slot) => !["cancelado", "concluido"].includes(slot.status)).map((slot) => slot.op_id).filter(Boolean));
  const unscheduledOps = activeOps.filter((op) => !scheduledOpIds.has(op.id));
  const slotsForSelectedDay = data.slots
    .filter((slot) => (slot.data || slot.data_inicio) === selectedDay && slot.status !== "cancelado")
    .sort((a, b) => `${a.linha_nome || ""}-${a.hora_inicio || ""}`.localeCompare(`${b.linha_nome || ""}-${b.hora_inicio || ""}`));
  const slotsByLine = activeLines.map((line) => ({
    line,
    slots: slotsForSelectedDay.filter((slot) => slot.linha_id === line.id),
  }));

  useEffect(() => {
    const current = new URLSearchParams(location.search).get("tab");
    if (["grade", "ops", "agenda", "config"].includes(current)) setTab(current);
  }, [location.search]);

  useEffect(() => {
    setSelectedDay(weekStart);
    setCalendarForm((form) => ({ ...form, data_inicio: weekStart, data_fim: weekEnd }));
  }, [weekStart, weekEnd]);

  const filteredOps = activeOps.filter(op => {
    if (!search.trim()) return true;
    const q = search.toLowerCase();
    return `${op.numero_op} ${op.cliente_nome} ${op.project_name} ${(op.items || []).map(i => i.item).join(" ")}`.toLowerCase().includes(q);
  });

  const ensureCalendar = async (linhaId) => {
    const semana = isoWeekKey(weekStart);
    const existing = await api.get("/pcp/calendario", { params: { semana, linha_id: linhaId } }).catch(() => ({ data: [] }));
    if (Array.isArray(existing.data) && existing.data.length > 0) return;
    await api.post("/pcp/calendario", { semana, linha_id: linhaId }).catch((err) => {
      if (err.response?.status !== 409) throw err;
    });
  };

  const scheduleOp = async (op, index) => {
    const alreadyScheduled = data.slots.some(slot => slot.op_id === op.id && !["cancelado", "concluido"].includes(slot.status));
    if (alreadyScheduled) {
      toast.info("Esta OP ja esta programada na semana.");
      return;
    }
    if (!activeLines.length) {
      toast.error("Cadastre ou ative ao menos uma linha antes de agendar.");
      return;
    }
    const line = activeLines[index % activeLines.length];
    const item = op.items?.[0] || {};
    const remaining = Math.max(Number(item.qtd_planejada || 0) - Number(item.qtd_produzida || 0), 0);
    setSchedulingId(op.id);
    try {
      await ensureCalendar(line.id);
      await api.post("/pcp/programacao", {
        op_id: op.id,
        linha_id: line.id,
        data: selectedDay,
        hora_inicio: "07:00",
        hora_fim: "17:00",
        turno: "integral",
        qtd_planejada: remaining || Number(item.qtd_planejada || 0) || 1,
        observacoes: "Agendado automaticamente pelo Planejamento PCP.",
      });
      toast.success(`OP ${op.numero_op || ""} agendada em ${line.nome}.`);
      await data.load();
      setTab("grade");
      navigate("/pcp/planejamento", { replace: true });
    } catch (err) {
      toast.error(err.response?.data?.detail || "Nao foi possivel agendar a OP.");
    } finally {
      setSchedulingId("");
    }
  };

  const toggleCalendarDay = (dia) => {
    setCalendarForm((form) => ({
      ...form,
      dias: form.dias.includes(dia) ? form.dias.filter((d) => d !== dia) : [...form.dias, dia],
    }));
  };

  const applyCalendar = async () => {
    if (!calendarForm.data_inicio || !calendarForm.data_fim) return toast.error("Informe o periodo.");
    if (!calendarForm.dias.length) return toast.error("Selecione ao menos um dia da semana.");
    const turnos = calendarForm.turnos === "2"
      ? [
          { nome: "Turno 1", hora_inicio: calendarForm.hora_inicio, hora_fim: "14:00", capacidade_pct: 50 },
          { nome: "Turno 2", hora_inicio: "14:00", hora_fim: calendarForm.hora_fim, capacidade_pct: 50 },
        ]
      : [{ nome: "Padrao", hora_inicio: calendarForm.hora_inicio, hora_fim: calendarForm.hora_fim, capacidade_pct: 100 }];
    setCalendarSaving(true);
    try {
      const { data: result } = await api.post("/pcp/calendario/aplicar-periodo", {
        data_inicio: calendarForm.data_inicio,
        data_fim: calendarForm.data_fim,
        linha_ids: calendarForm.linha_id === "all" ? [] : [calendarForm.linha_id],
        dias: calendarForm.dias,
        habilitado: calendarForm.habilitado,
        hora_inicio: calendarForm.hora_inicio,
        hora_fim: calendarForm.hora_fim,
        turnos,
        observacoes: calendarForm.observacoes,
      });
      toast.success(`Calendario aplicado em ${result.dias_aplicados || 0} dia(s).`);
      await data.load();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Nao foi possivel aplicar calendario.");
    } finally {
      setCalendarSaving(false);
    }
  };

  const openSlotEditor = (slot) => {
    setEditingSlot({
      ...slot,
      data: slot.data || slot.data_inicio || selectedDay,
      hora_inicio: slot.hora_inicio || "07:00",
      hora_fim: slot.hora_fim || "17:00",
      qtd_planejada: slot.qtd_planejada || 0,
      observacoes: slot.observacoes || "",
    });
  };

  const saveSlot = async () => {
    if (!editingSlot) return;
    setSavingSlot(true);
    try {
      await api.put(`/pcp/programacao/${editingSlot.id}`, {
        linha_id: editingSlot.linha_id,
        data: editingSlot.data,
        data_inicio: editingSlot.data,
        data_fim: editingSlot.data,
        hora_inicio: editingSlot.hora_inicio,
        hora_fim: editingSlot.hora_fim,
        qtd_planejada: Number(editingSlot.qtd_planejada || 0),
        observacoes: editingSlot.observacoes || "",
      });
      toast.success("Programacao atualizada.");
      setEditingSlot(null);
      await data.load();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Nao foi possivel atualizar o slot.");
    } finally {
      setSavingSlot(false);
    }
  };

  const cancelSlot = async (slot) => {
    setSavingSlot(true);
    try {
      await api.put(`/pcp/programacao/${slot.id}`, { status: "cancelado" });
      toast.success("Slot cancelado.");
      if (editingSlot?.id === slot.id) setEditingSlot(null);
      await data.load();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Nao foi possivel cancelar o slot.");
    } finally {
      setSavingSlot(false);
    }
  };

  return (
    <>
      <div className="mb-4 flex w-full gap-1 overflow-x-auto rounded-2xl bg-[#1f1f22] p-1 md:inline-flex md:w-auto">
        {[
          ["grade", "Grade Semanal"],
          ["ops", "Planejamento de OPs"],
          ["agenda", "Agendamento"],
          ["config", "Configuracoes"],
        ].map(([key, label]) => (
          <button key={key} onClick={() => setTab(key)} className={`rounded-xl px-6 py-2 text-sm font-black ${tab === key ? "bg-[#6485f2] text-white" : "text-zinc-500"}`}>
            {label}
          </button>
        ))}
      </div>

      {tab === "grade" && (
        <div className="space-y-4">
          <DarkCard>
            <div className="flex items-center justify-between">
              <span className="text-2xl font-black">-</span>
              <div className="flex gap-2">
                <Button variant="outline" className="border-white/20 bg-black text-white hover:bg-zinc-900" onClick={() => data.setDay(addDays(data.day, -7))}>Anterior</Button>
                <Button className="bg-zinc-100 text-[#6485f2] hover:bg-white" onClick={() => data.setDay(toYMD(new Date()))}>Hoje</Button>
                <Button variant="outline" className="border-white/20 bg-black text-white hover:bg-zinc-900" onClick={() => data.setDay(addDays(data.day, 7))}>Proxima</Button>
              </div>
            </div>
          </DarkCard>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-4">
            <Stat value={fmt(totalPlanejado)} label="Meta Semana" />
            <Stat value={fmt(data.slots.length)} label="Slots Planejados" />
            <Stat value={fmt(diasProgramados)} label="Dias com Prog." />
            <Stat value={fmt(activeOps.length)} label="Pedidos Ativos" />
          </div>
          <DarkCard>
            <div className="mb-4 flex gap-2 overflow-x-auto">
              {weekDays.map((day) => {
                const count = data.slots.filter((slot) => (slot.data || slot.data_inicio) === day.date && slot.status !== "cancelado").length;
                const isToday = day.date === toYMD(new Date());
                return (
                  <button
                    key={day.date}
                    type="button"
                    onClick={() => setSelectedDay(day.date)}
                    className={`min-w-[112px] rounded-xl border px-4 py-3 text-left transition ${selectedDay === day.date ? "border-[#6485f2] bg-[#6485f2] text-white" : "border-white/10 bg-black text-zinc-300 hover:bg-white/5"}`}
                  >
                    <span className="block text-xs font-black uppercase">{day.short}{isToday ? " - Hoje" : ""}</span>
                    <span className="mt-1 block font-mono text-sm">{dateLabel(day.date)}</span>
                    <span className="mt-2 block text-[11px] text-current opacity-70">{count} slot(s)</span>
                  </button>
                );
              })}
            </div>
            <div className="grid gap-3">
              {slotsByLine.length === 0 && <p className="rounded-lg border border-dashed border-white/15 p-6 text-center text-sm text-zinc-500">Nenhuma linha ativa para montar a grade.</p>}
              {slotsByLine.map(({ line, slots }) => (
                <div key={line.id} className="rounded-xl border border-white/10 bg-black p-4">
                  <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                    <div>
                      <h3 className="font-black">{line.nome}</h3>
                      <p className="text-xs text-zinc-500">{line.tipo || "geral"} - capacidade {fmt(line.capacidade_diaria)} {line.unidade_capacidade || "un"}/dia</p>
                    </div>
                    <Badge className={slots.length ? "bg-emerald-100 text-emerald-700" : "bg-zinc-100 text-zinc-700"}>{slots.length ? `${slots.length} slot(s)` : "Livre"}</Badge>
                  </div>
                  <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">
                    {slots.length === 0 ? (
                      <button type="button" onClick={() => setTab("agenda")} className="rounded-lg border border-dashed border-white/15 p-5 text-center text-sm font-black text-zinc-500 hover:border-[#6485f2] hover:text-white">
                        + produto
                      </button>
                    ) : slots.map((slot) => (
                      <button key={slot.id} type="button" onClick={() => openSlotEditor(slot)} className="rounded-lg border border-white/10 bg-[#1f1f22] p-3 text-left transition hover:border-[#6485f2]">
                        <div className="flex items-start justify-between gap-3">
                          <div className="min-w-0">
                            <p className="truncate font-black">{slot.produto_nome || slot.tipo || "Slot"}</p>
                            <p className="mt-1 text-xs text-zinc-500">{slot.op_numero || "-"} - {slot.hora_inicio || "--"} as {slot.hora_fim || "--"}</p>
                          </div>
                          <Badge className="bg-blue-100 text-blue-700">{slot.status || "planejado"}</Badge>
                        </div>
                        <div className="mt-3 flex items-center gap-2">
                          <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-zinc-300"><div className="h-full bg-[#00bf20]" style={{ width: `${slotProgress(slot)}%` }} /></div>
                          <span className="w-9 text-right text-xs text-zinc-400">{slotProgress(slot)}%</span>
                        </div>
                      </button>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </DarkCard>
          <DarkCard>
            <h2 className="mb-4 text-base font-black">Programacao Semanal Consolidada (Producao)</h2>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[980px] text-sm">
                <thead className="bg-zinc-100 text-[11px] uppercase tracking-wide text-zinc-500">
                  <tr>
                    {["Produto / Item", "OP / Lote", "Pedido Comercial", "Total do Lote (OP)", "Horas Programadas", "Meta Atual", "Programado na Semana", "Apontado (Realizado)", "Progresso"].map(h => (
                      <th key={h} className="p-3 text-left">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {data.slots.length === 0 ? (
                    <tr><td colSpan={9} className="p-7 text-center text-zinc-500">Nenhuma programacao para esta semana.</td></tr>
                  ) : data.slots.map(slot => (
                    <tr key={slot.id} className="border-t border-white/10">
                      <td className="p-3 font-black">{slot.produto_nome || "-"}</td>
                      <td className="p-3 font-mono text-xs">{slot.op_numero || "-"}</td>
                      <td className="p-3 font-mono text-xs">{slot.pedido_numero || "-"}</td>
                      <td className="p-3">{fmt(slot.qtd_planejada)}</td>
                      <td className="p-3">{slot.hora_inicio || "--"} - {slot.hora_fim || "--"}</td>
                      <td className="p-3">{fmt(slot.qtd_planejada)}</td>
                      <td className="p-3">{fmt(slot.qtd_planejada)}</td>
                      <td className="p-3">{fmt(slot.qtd_produzida)}</td>
                      <td className="p-3 font-black">{pct(Number(slot.qtd_produzida || 0), Number(slot.qtd_planejada || 0))}%</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </DarkCard>
        </div>
      )}

      {tab === "ops" && (
        <div className="space-y-4">
          <DarkCard>
            <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
              <div>
                <h1 className="text-xl font-black">Planejamento de OPs</h1>
                <p className="mt-1 text-sm text-zinc-500">OPs emitidas sem programacao aparecem primeiro; slots programados podem ser editados sem apagar historico.</p>
              </div>
              <Button className="bg-[#6485f2] font-black hover:bg-[#7593ff]" onClick={() => setTab("agenda")}>Agendar OP</Button>
            </div>
          </DarkCard>
          <div className="grid gap-3 md:grid-cols-3">
            <Stat value={fmt(unscheduledOps.length)} label="OPs sem programacao" />
            <Stat value={fmt(data.slots.filter((slot) => slot.status === "planejado").length)} label="Slots planejados" />
            <Stat value={fmt(data.slots.filter((slot) => slot.status === "em_execucao").length)} label="Em execucao" />
          </div>
          <DarkCard>
            <h2 className="mb-4 text-base font-black">Fila sem programacao</h2>
            <div className="space-y-2">
              {unscheduledOps.length === 0 && <p className="rounded-lg border border-dashed border-white/15 p-6 text-center text-sm text-emerald-300">Todas as OPs ativas ja tem uma posicao na grade.</p>}
              {unscheduledOps.map((op, idx) => {
                const item = op.items?.[0] || {};
                return (
                  <div key={op.id} className="flex flex-col gap-3 rounded-lg border border-white/10 bg-black p-4 md:flex-row md:items-center">
                    <Badge className="h-7 w-7 justify-center rounded-full bg-[#6485f2] p-0">{idx + 1}</Badge>
                    <div className="min-w-0 flex-1">
                      <p className="truncate font-black">{op.numero_op} - {item.item || op.project_name || "OP"}</p>
                      <p className="mt-1 text-xs text-zinc-500">{op.cliente_nome || "Cliente"} - {fmt(Math.max(Number(item.qtd_planejada || 0) - Number(item.qtd_produzida || 0), 0))} un. restantes</p>
                    </div>
                    <Button className="bg-[#6485f2] font-black hover:bg-[#7593ff]" disabled={schedulingId === op.id} onClick={() => scheduleOp(op, idx)}>
                      {schedulingId === op.id ? "Agendando..." : "Programar"}
                    </Button>
                  </div>
                );
              })}
            </div>
          </DarkCard>
          <DarkCard>
            <h2 className="mb-4 text-base font-black">Slots da semana</h2>
            <div className="grid gap-2">
              {data.slots.filter((slot) => slot.status !== "cancelado").map((slot) => (
                <div key={slot.id} className="grid gap-3 rounded-lg border border-white/10 bg-black p-4 md:grid-cols-[minmax(0,130px)_minmax(0,1fr)_minmax(96px,120px)_minmax(96px,120px)_100px] md:items-center">
                  <span className="block min-w-0 truncate font-mono text-sm" title={`${dateLabel(slot.data || slot.data_inicio)} - ${slot.hora_inicio}`}>
                    {dateLabel(slot.data || slot.data_inicio)} - {slot.hora_inicio}
                  </span>
                  <div className="min-w-0">
                    <p className="truncate font-black">{slot.produto_nome || slot.op_numero || "Slot"}</p>
                    <p className="truncate text-xs text-zinc-500">{slot.linha_nome} - {slot.op_numero || "-"}</p>
                  </div>
                  <Badge className="bg-blue-100 text-blue-700">{slot.status}</Badge>
                  <span className="font-mono text-sm">{fmt(slot.qtd_planejada)} un</span>
                  <Button variant="outline" className="border-white/20 bg-transparent text-white" onClick={() => openSlotEditor(slot)}>Editar</Button>
                </div>
              ))}
              {data.slots.length === 0 && <p className="p-8 text-center text-sm text-zinc-500">Nenhum slot na semana.</p>}
            </div>
          </DarkCard>
        </div>
      )}

      {tab === "agenda" && (
        <div className="space-y-4">
          <div>
            <h1 className="text-xl font-black">Pedidos em Aberto</h1>
            <p className="text-sm text-zinc-500">Ordenados por prioridade da planilha. Clique em Agendar para distribuir automaticamente nos slots livres.</p>
          </div>
          <div className="grid grid-cols-1 gap-2 md:grid-cols-[1fr_170px]">
            <div className="relative">
              <Search className="absolute left-3 top-3 h-4 w-4 text-zinc-500" />
              <Input value={search} onChange={e => setSearch(e.target.value)} placeholder="Buscar por produto, SKU, ID..." className="border-white/10 bg-[#1f1f22] pl-9 text-white" />
            </div>
            <Select defaultValue="all">
              <SelectTrigger className="border-white/10 bg-[#1f1f22] text-white"><SelectValue /></SelectTrigger>
              <SelectContent><SelectItem value="all">Todos os clientes</SelectItem></SelectContent>
            </Select>
          </div>
          <div className="space-y-3">
            {filteredOps.map((op, idx) => {
              const item = op.items?.[0] || {};
              const planned = Number(item.qtd_planejada || 0);
              const done = Number(item.qtd_produzida || 0);
              const progress = pct(done, planned);
              return (
                <DarkCard key={op.id} className="border-l-4 border-l-[#00bf20]">
                  <div className="flex items-center gap-4">
                    <Badge className="h-6 w-6 justify-center rounded-full bg-[#6485f2] p-0">{idx + 1}</Badge>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <h3 className="truncate text-base font-black">{item.item || op.project_name || op.numero_op}</h3>
                        <Badge className="bg-amber-100 text-amber-700">
                          {op.status === "aguardando_confirmacao_pcp" ? "Aguardando PCP" : op.status === "em_processo" ? "Producao Parcial" : "Programado"}
                        </Badge>
                        <Badge className="bg-sky-100 text-sky-700">{op.cliente_nome || "Cliente"}</Badge>
                      </div>
                      <p className="mt-1 text-xs text-zinc-500">{op.numero_pedido || op.numero_op} - {fmt(Math.round((planned || 0) / 17 || 0))}/h - Falta: {fmt(Math.max(planned - done, 0))} un</p>
                      <div className="mt-3 flex items-center gap-3">
                        <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-zinc-300"><div className="h-full bg-[#00bf20]" style={{ width: `${progress}%` }} /></div>
                        <span className="w-10 text-right text-xs text-zinc-400">{progress}%</span>
                      </div>
                    </div>
                    <Button
                      className="bg-[#6485f2] font-black hover:bg-[#7593ff]"
                      disabled={schedulingId === op.id}
                      onClick={() => scheduleOp(op, idx)}
                    >
                      {schedulingId === op.id ? "Agendando..." : "Agendar"}
                    </Button>
                  </div>
                </DarkCard>
              );
            })}
          </div>
        </div>
      )}

      {tab === "config" && (
        <div className="space-y-4">
          <DarkCard>
            <h2 className="mb-4 text-base font-black">Ajuste Rapido de Calendario e Turnos</h2>
            <div className="grid grid-cols-1 gap-3 md:grid-cols-4">
              <div>
                <Label>Data inicial</Label>
                <Input type="date" value={calendarForm.data_inicio} onChange={(e) => setCalendarForm((f) => ({ ...f, data_inicio: e.target.value }))} className="mt-1 border-white/10 bg-zinc-700 text-white" />
              </div>
              <div>
                <Label>Data final</Label>
                <Input type="date" value={calendarForm.data_fim} onChange={(e) => setCalendarForm((f) => ({ ...f, data_fim: e.target.value }))} className="mt-1 border-white/10 bg-zinc-700 text-white" />
              </div>
              <div>
                <Label>Linha</Label>
                <Select value={calendarForm.linha_id} onValueChange={(v) => setCalendarForm((f) => ({ ...f, linha_id: v }))}>
                  <SelectTrigger className="mt-1 border-white/10 bg-zinc-700 text-white"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">Todas as linhas</SelectItem>
                    {data.linhas.map((linha) => <SelectItem key={linha.id} value={linha.id}>{linha.nome}</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>
              <div>
                <Label>Turnos</Label>
                <Select value={calendarForm.turnos} onValueChange={(v) => setCalendarForm((f) => ({ ...f, turnos: v }))}>
                  <SelectTrigger className="mt-1 border-white/10 bg-zinc-700 text-white"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="1">1 turno</SelectItem>
                    <SelectItem value="2">2 turnos</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>
            <div className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-3">
              <div>
                <Label>Inicio</Label>
                <Input type="time" value={calendarForm.hora_inicio} onChange={(e) => setCalendarForm((f) => ({ ...f, hora_inicio: e.target.value }))} className="mt-1 border-white/10 bg-zinc-700 text-white" />
              </div>
              <div>
                <Label>Fim</Label>
                <Input type="time" value={calendarForm.hora_fim} onChange={(e) => setCalendarForm((f) => ({ ...f, hora_fim: e.target.value }))} className="mt-1 border-white/10 bg-zinc-700 text-white" />
              </div>
              <div>
                <Label>Status do dia</Label>
                <Select value={calendarForm.habilitado ? "on" : "off"} onValueChange={(v) => setCalendarForm((f) => ({ ...f, habilitado: v === "on" }))}>
                  <SelectTrigger className="mt-1 border-white/10 bg-zinc-700 text-white"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="on">Operando</SelectItem>
                    <SelectItem value="off">Bloqueado</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>
            <div className="mt-4 flex flex-wrap gap-2">
              {[
                ["seg", "Segunda"], ["ter", "Terca"], ["qua", "Quarta"], ["qui", "Quinta"], ["sex", "Sexta"], ["sab", "Sabado"], ["dom", "Domingo"],
              ].map(([key, label]) => (
                <button key={key} type="button" onClick={() => toggleCalendarDay(key)} className={`rounded-lg px-4 py-2 text-sm font-black ${calendarForm.dias.includes(key) ? "bg-emerald-100 text-emerald-800" : "border border-zinc-600 bg-black text-zinc-400"}`}>
                  {label}
                </button>
              ))}
            </div>
            <Input value={calendarForm.observacoes} onChange={(e) => setCalendarForm((f) => ({ ...f, observacoes: e.target.value }))} placeholder="Observacoes do ajuste" className="mt-4 border-white/10 bg-zinc-700 text-white" />
            <Button className="mt-5 bg-[#00bf20] px-8 font-black hover:bg-[#00a91c]" disabled={calendarSaving} onClick={applyCalendar}>
              {calendarSaving ? "Aplicando..." : "Aplicar Calendario"}
            </Button>
          </DarkCard>
          <DarkCard>
            <h2 className="mb-4 text-base font-black text-red-400">Limpar Programacao em Lote</h2>
            <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
              <Select defaultValue="all"><SelectTrigger className="border-white/10 bg-zinc-700 text-white"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="all">Todas as Linhas</SelectItem></SelectContent></Select>
              <Input type="date" className="border-white/10 bg-zinc-700 text-white" />
              <Input type="date" className="border-white/10 bg-zinc-700 text-white" />
            </div>
            <Button className="mt-5 w-full bg-red-100 font-black text-red-600 hover:bg-red-200">Apagar Programacao do Periodo</Button>
          </DarkCard>
          <Button className="bg-[#00bf20] px-8 font-black hover:bg-[#00a91c]">Salvar Configuracoes</Button>
        </div>
      )}

      <Dialog open={!!editingSlot} onOpenChange={(open) => !open && setEditingSlot(null)}>
        <DialogContent className="max-w-2xl bg-[#1f1f22] text-white">
          <DialogHeader>
            <DialogTitle>Editar programacao</DialogTitle>
          </DialogHeader>
          {editingSlot && (
            <div className="space-y-4">
              <div className="rounded-lg border border-white/10 bg-black p-3">
                <p className="font-black">{editingSlot.produto_nome || editingSlot.op_numero || "Slot"}</p>
                <p className="mt-1 text-xs text-zinc-500">{editingSlot.op_numero || "-"} - {editingSlot.pedido_numero || "-"}</p>
              </div>
              <div className="grid gap-3 md:grid-cols-2">
                <div>
                  <Label>Linha</Label>
                  <Select value={editingSlot.linha_id} onValueChange={(value) => setEditingSlot((slot) => ({ ...slot, linha_id: value }))}>
                    <SelectTrigger className="mt-1 border-white/10 bg-zinc-700 text-white"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      {activeLines.map((linha) => <SelectItem key={linha.id} value={linha.id}>{linha.nome}</SelectItem>)}
                    </SelectContent>
                  </Select>
                </div>
                <div>
                  <Label>Data</Label>
                  <Input type="date" value={editingSlot.data} onChange={(e) => setEditingSlot((slot) => ({ ...slot, data: e.target.value }))} className="mt-1 border-white/10 bg-zinc-700 text-white" />
                </div>
                <div>
                  <Label>Inicio</Label>
                  <Input type="time" value={editingSlot.hora_inicio} onChange={(e) => setEditingSlot((slot) => ({ ...slot, hora_inicio: e.target.value }))} className="mt-1 border-white/10 bg-zinc-700 text-white" />
                </div>
                <div>
                  <Label>Fim</Label>
                  <Input type="time" value={editingSlot.hora_fim} onChange={(e) => setEditingSlot((slot) => ({ ...slot, hora_fim: e.target.value }))} className="mt-1 border-white/10 bg-zinc-700 text-white" />
                </div>
                <div>
                  <Label>Quantidade planejada</Label>
                  <Input type="number" value={editingSlot.qtd_planejada} onChange={(e) => setEditingSlot((slot) => ({ ...slot, qtd_planejada: e.target.value }))} className="mt-1 border-white/10 bg-zinc-700 text-white" />
                </div>
                <div>
                  <Label>Duracao</Label>
                  <div className="mt-1 rounded-lg border border-white/10 bg-black px-3 py-2 text-sm text-zinc-300">
                    {Math.round(minutesBetween(editingSlot.hora_inicio, editingSlot.hora_fim) / 60 * 10) / 10}h
                  </div>
                </div>
              </div>
              <div>
                <Label>Observacoes</Label>
                <Input value={editingSlot.observacoes} onChange={(e) => setEditingSlot((slot) => ({ ...slot, observacoes: e.target.value }))} className="mt-1 border-white/10 bg-zinc-700 text-white" />
              </div>
            </div>
          )}
          <DialogFooter className="gap-2">
            <Button variant="outline" className="border-red-500/40 bg-transparent text-red-300 hover:bg-red-500/10" disabled={savingSlot || !editingSlot} onClick={() => cancelSlot(editingSlot)}>
              <XCircle className="mr-2 h-4 w-4" />Cancelar slot
            </Button>
            <Button variant="outline" className="border-white/20 bg-transparent text-white" onClick={() => setEditingSlot(null)}>Fechar</Button>
            <Button className="bg-[#6485f2] font-black hover:bg-[#7593ff]" disabled={savingSlot || !editingSlot} onClick={saveSlot}>
              {savingSlot ? "Salvando..." : "Salvar"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

function HorizonPage({ data }) {
  const [weeks, setWeeks] = useState(10);
  const [sim, setSim] = useState({ dias: 30, linhas_extras: 0, turnos: 1, sabados: 0 });
  const [freezingId, setFreezingId] = useState("");
  const activeLines = data.linhas.filter(linha => linha.status !== "inativa");
  const backlog = data.ops.filter(op => ["aberta", "em_processo", "pausada", "aguardando_confirmacao_pcp"].includes(op.status));
  const baseCapacity = activeLines.reduce((sum, linha) => sum + Number(linha.capacidade_diaria || 0), 0);
  const projectedDays = Math.max(1, weeks * 5);
  const projectedCapacity = baseCapacity * projectedDays;
  const scheduledByLine = activeLines.map((linha) => {
    const planned = data.slots
      .filter((slot) => slot.linha_id === linha.id && slot.status !== "cancelado")
      .reduce((sum, slot) => sum + Number(slot.qtd_planejada || 0), 0);
    const pctLine = pct(planned, Number(linha.capacidade_diaria || 0) * 5);
    return { linha, planned, pctLine };
  });
  const simulatedCapacity = ((baseCapacity + Number(sim.linhas_extras || 0) * 5000) * Math.max(1, Number(sim.turnos || 1)) * Math.max(1, Number(sim.dias || 1) / 5)) + (Number(sim.sabados || 0) * baseCapacity);
  const horizonButtonClass = "h-9 w-9 min-w-9 border border-slate-200 bg-white text-slate-950 shadow-sm hover:bg-slate-50 dark:border-white/15 dark:bg-slate-950/70 dark:text-white dark:hover:bg-white/10";

  const ensureCalendar = async (linhaId, date) => {
    const semana = isoWeekKey(date);
    const existing = await api.get("/pcp/calendario", { params: { semana, linha_id: linhaId } }).catch(() => ({ data: [] }));
    if (Array.isArray(existing.data) && existing.data.length > 0) return;
    await api.post("/pcp/calendario", { semana, linha_id: linhaId }).catch((err) => {
      if (err.response?.status !== 409) throw err;
    });
  };

  const freezeBacklog = async (op, idx) => {
    if (!activeLines.length) return toast.error("Nao ha linha ativa para congelar o backlog.");
    const line = activeLines[idx % activeLines.length];
    const targetDate = addDays(startOfWeek(data.day), Math.floor(idx / Math.max(activeLines.length, 1)) * 7);
    const item = op.items?.[0] || {};
    const qty = Math.max(Number(item.qtd_planejada || 0) - Number(item.qtd_produzida || 0), 0) || Number(item.qtd_planejada || 0) || 1;
    setFreezingId(op.id);
    try {
      await ensureCalendar(line.id, targetDate);
      await api.post("/pcp/programacao", {
        op_id: op.id,
        linha_id: line.id,
        data: targetDate,
        hora_inicio: "07:00",
        hora_fim: "17:00",
        turno: "integral",
        qtd_planejada: qty,
        observacoes: "Congelado pelo Horizonte de Producao.",
      });
      toast.success(`Backlog congelado em ${line.nome} na semana de ${dateLabel(targetDate)}.`);
      await data.load();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Nao foi possivel congelar este backlog.");
    } finally {
      setFreezingId("");
    }
  };

  return (
    <div className="space-y-4">
      <DarkCard>
        <div className="flex flex-col gap-3 md:flex-row md:items-center">
          <span className="text-sm font-bold text-zinc-500">Horizonte:</span>
          <Button
            type="button"
            variant="outline"
            size="icon"
            aria-label="Reduzir horizonte"
            className={horizonButtonClass}
            onClick={() => setWeeks(w => Math.max(1, w - 1))}
          >
            -
          </Button>
          <span className="font-black">{weeks} semanas</span>
          <Button
            type="button"
            variant="outline"
            size="icon"
            aria-label="Aumentar horizonte"
            className={horizonButtonClass}
            onClick={() => setWeeks(w => w + 1)}
          >
            +
          </Button>
          <div className="flex flex-wrap gap-4 text-xs text-zinc-500 md:ml-auto">
            <span><b className="text-blue-300">■</b> Linha propria do pedido</span>
            <span><b className="text-violet-300">■</b> Linha sugerida automaticamente</span>
            <span><b className="text-green-500">●</b> Insumo OK</span>
            <span><b className="text-yellow-500">●</b> Insumo pendente</span>
          </div>
        </div>
      </DarkCard>
      <DarkCard>
        <div className="grid gap-3 md:grid-cols-4">
          <Stat value={fmt(projectedCapacity)} label="Capacidade projetada" />
          <Stat value={fmt(backlog.length)} label="Backlog ativo" />
          <Stat value={fmt(data.slots.length)} label="Slots no horizonte atual" />
          <Stat value={fmt(activeLines.length)} label="Linhas ativas" />
        </div>
      </DarkCard>
      <DarkCard>
        <h2 className="mb-5 text-base font-black">Capacidade por Linha</h2>
        <div className="space-y-5">
          {(scheduledByLine.length ? scheduledByLine : [{ linha: { nome: "Linha 1", capacidade_diaria: 6000 }, planned: 0, pctLine: 0 }]).map(({ linha, planned, pctLine }, idx) => (
            <div key={linha.id || idx} className="grid grid-cols-1 gap-2 md:grid-cols-[minmax(0,120px)_minmax(0,1fr)_minmax(150px,180px)] md:items-center md:gap-4">
              <span className="block min-w-0 truncate font-black" title={linha.nome}>{linha.nome}</span>
              <div className="h-2 overflow-hidden rounded-full bg-zinc-300"><div className="h-full bg-[#6485f2]" style={{ width: `${Math.min(100, pctLine)}%` }} /></div>
              <span className="block min-w-0 truncate text-right text-xs text-zinc-500">{fmt(planned)} / {fmt(Number(linha.capacidade_diaria || 0) * 5)} un na semana</span>
            </div>
          ))}
        </div>
      </DarkCard>
      <DarkCard>
        <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <h2 className="text-base font-black">Simulador de Capacidade</h2>
            <p className="mt-1 text-sm text-zinc-500">Sandbox de decisao: calcula impacto de linha extra, segundo turno e sabados sem gravar no planejamento.</p>
          </div>
          <div className="grid w-full gap-3 sm:grid-cols-2 lg:w-auto lg:grid-cols-4">
            <label className="text-xs font-bold text-zinc-500">Dias
              <Input type="number" min="1" value={sim.dias} onChange={(e) => setSim((s) => ({ ...s, dias: e.target.value }))} className="mt-1 border-white/10 bg-zinc-700 text-white" />
            </label>
            <label className="text-xs font-bold text-zinc-500">Linhas extras
              <Input type="number" min="0" value={sim.linhas_extras} onChange={(e) => setSim((s) => ({ ...s, linhas_extras: e.target.value }))} className="mt-1 border-white/10 bg-zinc-700 text-white" />
            </label>
            <label className="text-xs font-bold text-zinc-500">Turnos
              <Select value={String(sim.turnos)} onValueChange={(value) => setSim((s) => ({ ...s, turnos: value }))}>
                <SelectTrigger className="mt-1 border-white/10 bg-zinc-700 text-white"><SelectValue /></SelectTrigger>
                <SelectContent><SelectItem value="1">1 turno</SelectItem><SelectItem value="2">2 turnos</SelectItem></SelectContent>
              </Select>
            </label>
            <label className="text-xs font-bold text-zinc-500">Sabados extras
              <Input type="number" min="0" value={sim.sabados} onChange={(e) => setSim((s) => ({ ...s, sabados: e.target.value }))} className="mt-1 border-white/10 bg-zinc-700 text-white" />
            </label>
          </div>
        </div>
        <div className="mt-4 grid gap-3 md:grid-cols-3">
          <Stat value={fmt(Math.round(simulatedCapacity))} label="Capacidade simulada" />
          <Stat value={`${projectedCapacity ? Math.round(((simulatedCapacity - projectedCapacity) / projectedCapacity) * 100) : 0}%`} label="Ganho vs atual" />
          <Stat value={fmt(Math.max(0, Math.round(simulatedCapacity - projectedCapacity)))} label="Ganho absoluto" />
        </div>
      </DarkCard>
      <DarkCard>
        <h2 className="text-xl font-black">Fila de Backlog (Prioridade)</h2>
        <p className="mb-5 text-sm text-zinc-500">Arraste pela alca para reordenar, ou use Classificar Prioridade para saltos grandes.</p>
        <div className="space-y-2">
          {backlog.map((op, idx) => {
            const item = op.items?.[0] || {};
            return (
              <div key={op.id} className="grid grid-cols-[28px_32px_1fr] items-center gap-3 rounded-lg border border-white/10 bg-black px-4 py-3 md:grid-cols-[28px_32px_1fr_110px_110px_92px]">
                <span className="text-zinc-500">::</span>
                <Badge className="h-6 w-6 justify-center rounded-full bg-[#6485f2] p-0">{idx + 1}</Badge>
                <div className="min-w-0">
                  <p className="truncate font-black"><span className="mr-2 text-yellow-500">●</span>{item.item || op.project_name || op.numero_op}</p>
                  <p className="text-xs text-zinc-500">{op.cliente_nome || "Cliente"} - {fmt(Math.max(Number(item.qtd_planejada || 0) - Number(item.qtd_produzida || 0), 0))} un. restantes</p>
                </div>
                <Badge className="bg-violet-100 text-violet-700">Linha {(idx % 3) + 1}</Badge>
                <span className="text-xs text-zinc-500">semana de {dateLabel(addDays(startOfWeek(data.day), Math.floor(idx / Math.max(activeLines.length || 1, 1)) * 7))}</span>
                <Button className="bg-[#6485f2] font-black hover:bg-[#7593ff]" disabled={freezingId === op.id} onClick={() => freezeBacklog(op, idx)}>
                  <Lock className="mr-2 h-4 w-4" />{freezingId === op.id ? "Congelando..." : "Congelar"}
                </Button>
              </div>
            );
          })}
          {backlog.length === 0 && <p className="rounded-lg border border-dashed border-white/15 p-8 text-center text-sm text-zinc-500">Nenhum pedido em backlog no momento.</p>}
        </div>
      </DarkCard>
    </div>
  );
}

function ControlOpsPage({ data }) {
  const navigate = useNavigate();
  const location = useLocation();
  const opIdFromUrl = new URLSearchParams(location.search).get("op") || "";
  const activeOps = data.ops
    .filter(op => ["aberta", "em_processo", "pausada", "aguardando_confirmacao_pcp"].includes(op.status))
    .sort((a, b) => (b.id === opIdFromUrl) - (a.id === opIdFromUrl));
  return (
    <div className="space-y-4">
      <div className="flex flex-col items-start justify-between gap-4 md:flex-row">
        <div>
          <h1 className="text-3xl font-black">Controle de OPs Ativas</h1>
          <p className="mt-1 text-sm text-zinc-500">Visualizador das OPs emitidas para acompanhamento por nivel de OP.</p>
        </div>
      </div>
      <div className="flex w-full overflow-x-auto rounded-lg bg-zinc-100 p-1 md:inline-flex md:w-auto">
        <button className="rounded-md bg-[#1f1f22] px-8 py-2 font-black text-white">OPs Ativas</button>
        <button className="px-8 py-2 font-black text-zinc-500">Checklist de Ordens</button>
      </div>
      <DarkCard>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[980px] text-sm">
            <thead>
              <tr className="border-b border-white/10 text-left text-xs uppercase text-zinc-500">
                {["OP / Lote", "Cliente", "Produto / Descricao", "Linha", "Pedido Comercial", "Progresso Realizado", "Status da OP", "Acoes"].map(h => <th key={h} className="p-4">{h}</th>)}
              </tr>
            </thead>
            <tbody>
              <tr><td colSpan={8} className="bg-zinc-100 p-3 text-xs font-black uppercase text-zinc-500">OPs emitidas em aberto ({activeOps.length})</td></tr>
              {activeOps.map(op => {
                const item = op.items?.[0] || {};
                const done = Number(item.qtd_produzida || 0);
                const planned = Number(item.qtd_planejada || 0);
                const progress = pct(done, planned);
                return (
                  <tr key={op.id} className={`border-b border-white/20 ${op.id === opIdFromUrl ? "bg-[#6485f2]/15" : ""}`}>
                    <td className="p-4 font-black">{op.numero_op}</td>
                    <td className="p-4">{op.cliente_nome || "-"}</td>
                    <td className="p-4 font-black">{item.item || op.project_name || "-"}<p className="text-xs font-normal text-zinc-500">SKU: {item.codigo_kuryos || "-"}</p></td>
                    <td className="p-4">
                      <Badge className="bg-zinc-100 text-zinc-700">{op.linha_nome || "Sem linha"}</Badge>
                    </td>
                    <td className="p-4"><Badge className="bg-violet-100 text-violet-700">#{op.numero_pedido || "-"}</Badge></td>
                    <td className="p-4">
                      <div className="mb-1 flex justify-between text-xs font-black"><span>{fmt(done)} / {fmt(planned)} un</span><span>{progress}%</span></div>
                      <div className="h-2 overflow-hidden rounded-full bg-zinc-300"><div className="h-full bg-[#00bf20]" style={{ width: `${progress}%` }} /></div>
                    </td>
                    <td className="p-4">
                      <Badge className="bg-blue-100 text-blue-700">{op.status || "-"}</Badge>
                    </td>
                    <td className="p-4"><Button variant="outline" size="sm" className="border-white/20 bg-transparent text-white" onClick={() => navigate(`/ops/${op.id}`)}>Ver OP</Button></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </DarkCard>
    </div>
  );
}

function HistorySalesPage({ data }) {
  const navigate = useNavigate();
  const [search, setSearch] = useState("");
  const rows = useMemo(() => data.historico?.rows || [], [data.historico?.rows]);
  const kpis = data.historico?.kpis || {};

  const filteredRows = useMemo(() => {
    if (!search.trim()) return rows;
    const q = search.toLowerCase();
    return rows.filter((row) => `${row.op_numero || ""} ${row.pedido_numero || ""} ${row.cliente_nome || ""} ${row.produto || ""} ${row.sku || ""} ${row.observacoes || ""}`.toLowerCase().includes(q));
  }, [rows, search]);

  const salesOrders = useMemo(() => data.orders.filter((order) => {
    const hay = `${order.numero_pedido || ""} ${order.cliente?.nome || ""} ${order.project_name || ""} ${(order.items || []).map((item) => `${item.item || ""} ${item.codigo_kuryos || ""}`).join(" ")}`.toLowerCase();
    return !search.trim() || hay.includes(search.toLowerCase());
  }), [data.orders, search]);

  const statusBadgeClass = (status) => {
    if (status === "concluido") return "bg-emerald-100 text-emerald-700";
    if (status === "em_producao") return "bg-amber-100 text-amber-700";
    if (status === "confirmado") return "bg-blue-100 text-blue-700";
    if (status === "cancelado") return "bg-red-100 text-red-700";
    return "bg-zinc-100 text-zinc-700";
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <h1 className="text-3xl font-black">Historico / Pedidos de Vendas</h1>
          <p className="mt-1 text-sm text-zinc-500">Visao do PCP sobre pedidos comerciais, apontamentos, perdas e pausas de producao.</p>
        </div>
        <Button variant="outline" className="border-white/20 bg-transparent text-white" onClick={data.load}>
          <RefreshCw className="mr-2 h-4 w-4" />Atualizar
        </Button>
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat value={fmt(kpis.registros)} label="Registros" />
        <Stat value={fmt(kpis.total_produzido)} label="Produzido" />
        <Stat value={fmt(kpis.total_perdas)} label="Perdas" />
        <Stat value={fmt(kpis.pedidos_unicos || salesOrders.length)} label="Pedidos" />
      </div>

      <DarkCard>
        <div className="relative">
          <Search className="absolute left-3 top-3 h-4 w-4 text-zinc-500" />
          <Input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Buscar por pedido, OP, cliente, produto, SKU..." className="border-white/10 bg-[#1f1f22] pl-9 text-white" />
        </div>
      </DarkCard>

      <DarkCard className="p-0">
        <div className="border-b border-white/10 px-4 py-4 text-xs font-black uppercase tracking-wide text-zinc-500">Pedidos de vendas ({salesOrders.length})</div>
        <div className="divide-y divide-white/10">
          {salesOrders.slice(0, 80).map((order) => (
            <button
              key={order.id}
              className="grid w-full grid-cols-1 gap-3 px-4 py-3 text-left hover:bg-white/5 md:grid-cols-[minmax(0,132px)_minmax(0,1fr)_minmax(112px,130px)_minmax(86px,120px)_24px] md:items-center"
              onClick={() => navigate(`/orders/${order.id}`)}
            >
              <span className="block min-w-0 overflow-hidden font-mono text-sm font-black text-[#6485f2]">
                <span className="block truncate" title={`#${order.numero_pedido || order.id}`}>#{order.numero_pedido || order.id}</span>
              </span>
              <span className="block min-w-0 overflow-hidden">
                <b className="block truncate" title={order.cliente?.nome || order.cliente?.razao_social || "Cliente"}>
                  {order.cliente?.nome || order.cliente?.razao_social || "Cliente"}
                </b>
                <span
                  className="block truncate text-xs text-zinc-500"
                  title={(order.items || []).map((item) => item.item).filter(Boolean).join(" | ") || order.project_name || "-"}
                >
                  {(order.items || []).map((item) => item.item).filter(Boolean).join(" | ") || order.project_name || "-"}
                </span>
              </span>
              <span className="block min-w-0 overflow-hidden">
                <Badge className={`${statusBadgeClass(order.status)} max-w-full truncate`}>
                  {String(order.status || "rascunho").replaceAll("_", " ")}
                </Badge>
              </span>
              <span className="block min-w-0 truncate text-xs text-zinc-500">{order.op_id ? "OP emitida" : "Sem OP"}</span>
              <ArrowRight className="h-4 w-4 shrink-0 justify-self-start text-zinc-500 md:justify-self-end" />
            </button>
          ))}
          {salesOrders.length === 0 && <p className="p-8 text-center text-sm text-zinc-500">Nenhum pedido de venda encontrado.</p>}
        </div>
      </DarkCard>

      <DarkCard className="p-0">
        <div className="border-b border-white/10 px-4 py-4 text-xs font-black uppercase tracking-wide text-zinc-500">Historico de apontamentos ({filteredRows.length})</div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[980px] text-sm">
            <thead className="bg-zinc-100 text-left text-[11px] uppercase tracking-wide text-zinc-500">
              <tr>{["Data", "Hora", "Tipo", "OP", "Pedido", "Cliente", "Produto", "Qtd", "Obs"].map((h) => <th key={h} className="p-3">{h}</th>)}</tr>
            </thead>
            <tbody>
              {filteredRows.map((row, idx) => (
                <tr key={`${row.tipo}-${row.id || idx}`} className="border-b border-white/10">
                  <td className="p-3 font-mono text-xs">{row.data || "-"}</td>
                  <td className="p-3 font-mono text-xs">{row.hora || "-"}</td>
                  <td className="p-3"><Badge className={row.tipo === "perda" ? "bg-red-100 text-red-700" : row.tipo === "pausa" ? "bg-amber-100 text-amber-700" : "bg-emerald-100 text-emerald-700"}>{row.tipo}</Badge></td>
                  <td className="p-3 font-black">{row.op_numero || "-"}</td>
                  <td className="p-3 text-[#6485f2]">#{row.pedido_numero || "-"}</td>
                  <td className="p-3">{row.cliente_nome || "-"}</td>
                  <td className="p-3 font-black">{row.produto || "-"}<p className="text-xs font-normal text-zinc-500">SKU: {row.sku || "-"}</p></td>
                  <td className="p-3 text-right font-mono font-black">{fmt(row.qtd)}</td>
                  <td className="p-3 text-xs text-zinc-500">{row.observacoes || "-"}</td>
                </tr>
              ))}
              {filteredRows.length === 0 && <tr><td colSpan={9} className="p-8 text-center text-zinc-500">Nenhum registro no periodo carregado.</td></tr>}
            </tbody>
          </table>
        </div>
      </DarkCard>
    </div>
  );
}

function EmitOPPage({ data }) {
  const navigate = useNavigate();
  const [search, setSearch] = useState("");
  const [emittingId, setEmittingId] = useState("");

  const orders = useMemo(() => data.orders.filter((order) => {
    if (!["confirmado", "em_producao"].includes(order.status)) return false;
    const hay = `${order.numero_pedido || ""} ${order.cliente?.nome || ""} ${order.project_name || ""} ${(order.items || []).map((item) => `${item.item || ""} ${item.codigo_kuryos || ""}`).join(" ")}`.toLowerCase();
    return !search.trim() || hay.includes(search.toLowerCase());
  }), [data.orders, search]);

  const emit = async (order) => {
    setEmittingId(order.id);
    try {
      const { data: op } = await api.post(`/orders/${order.id}/create-op`);
      toast.success(`OP ${op.numero_op || ""} enviada ao PCP.`);
      await data.load();
      navigate(`/pcp/controle-ops?op=${op.id}`);
    } catch (err) {
      const detail = err.response?.data?.detail;
      toast.error(typeof detail === "string" ? detail : detail?.message || "Nao foi possivel emitir a OP.");
    } finally {
      setEmittingId("");
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
        <div>
          <h1 className="text-3xl font-black">Emitir OP</h1>
          <p className="mt-1 text-sm text-zinc-500">Clone funcional da emissao do PCP: pedido confirmado vira OP uma unica vez e segue para Controle de OPs.</p>
        </div>
        <Button variant="outline" className="border-white/20 bg-transparent text-white" onClick={data.load}>
          <RefreshCw className="mr-2 h-4 w-4" />Atualizar
        </Button>
      </div>

      <DarkCard>
        <div className="relative">
          <Search className="absolute left-3 top-3 h-4 w-4 text-zinc-500" />
          <Input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Buscar pedido confirmado por cliente, SKU ou produto..." className="border-white/10 bg-[#1f1f22] pl-9 text-white" />
        </div>
      </DarkCard>

      <div className="grid gap-3">
        {orders.map((order) => {
          const items = order.items || [];
          const total = items.reduce((sum, item) => sum + Number(item.qtd || item.qtd_planejada || 0), 0);
          return (
            <DarkCard key={order.id} className="border-l-4 border-[#6485f2]">
              <div className="grid gap-4 lg:grid-cols-[1fr_220px] lg:items-center">
                <div className="min-w-0">
                  <div className="mb-2 flex flex-wrap items-center gap-2">
                    <Badge className="bg-violet-100 text-violet-700">Pedido #{order.numero_pedido || order.id}</Badge>
                    <Badge className={order.op_id ? "bg-emerald-100 text-emerald-700" : "bg-blue-100 text-blue-700"}>{order.op_id ? "OP ja emitida" : "Pronto para emitir"}</Badge>
                    <Badge className="bg-zinc-100 text-zinc-700">{fmt(total)} un</Badge>
                  </div>
                  <h2 className="truncate text-xl font-black">{order.cliente?.nome || order.cliente?.razao_social || "Cliente"}</h2>
                  <p className="mt-1 text-sm text-zinc-500">{order.project_name || "Pedido comercial confirmado"}</p>
                  <div className="mt-3 grid gap-2 md:grid-cols-2">
                    {items.slice(0, 4).map((item, idx) => (
                      <div key={`${order.id}-${idx}`} className="rounded-lg border border-white/10 bg-black px-3 py-2">
                        <p className="truncate text-sm font-black">{item.item || "Item"}</p>
                        <p className="text-xs text-zinc-500">SKU: {item.codigo_kuryos || "A definir"} | Qtd: {fmt(item.qtd || item.qtd_planejada || 0)}</p>
                      </div>
                    ))}
                  </div>
                </div>
                <div className="flex flex-col gap-2">
                  {order.op_id ? (
                    <Button className="bg-[#6485f2] font-black hover:bg-[#7593ff]" onClick={() => navigate(`/pcp/controle-ops?op=${order.op_id}`)}>
                      <Factory className="mr-2 h-4 w-4" />Abrir no PCP
                    </Button>
                  ) : (
                    <Button className="bg-[#00bf20] font-black hover:bg-[#00a91c]" disabled={emittingId === order.id} onClick={() => emit(order)}>
                      <Factory className="mr-2 h-4 w-4" />{emittingId === order.id ? "Emitindo..." : "Gerar OP"}
                    </Button>
                  )}
                  <Button variant="outline" className="border-white/20 bg-transparent text-white" onClick={() => navigate(`/orders/${order.id}`)}>
                    <ClipboardList className="mr-2 h-4 w-4" />Ver pedido
                  </Button>
                </div>
              </div>
            </DarkCard>
          );
        })}
        {orders.length === 0 && (
          <DarkCard>
            <div className="py-10 text-center">
              <Factory className="mx-auto mb-3 h-10 w-10 text-zinc-500" />
              <p className="font-black">Nenhum pedido confirmado disponivel para emissao.</p>
              <p className="mt-1 text-sm text-zinc-500">Pedidos em rascunho ou aguardando cliente/comercial nao entram na emissao de OP.</p>
            </div>
          </DarkCard>
        )}
      </div>
    </div>
  );
}

function valueText(value, fallback = "-") {
  if (value === null || value === undefined || value === "") return fallback;
  return value;
}

function statusClass(status) {
  if (status === "ativo") return "bg-emerald-100 text-emerald-700";
  if (status === "descontinuado") return "bg-red-100 text-red-700";
  if (status === "suspenso") return "bg-amber-100 text-amber-700";
  return "bg-zinc-100 text-zinc-700";
}

function skuClientName(sku) {
  return sku.cliente_nome || sku.cliente?.nome || sku.cliente_name || sku.cliente_id || "-";
}

function skuVolume(sku) {
  return sku.volume || sku.apresentacao_volume || sku.volume_ml || sku.tamanho || "";
}

function ProductDialog({ open, onOpenChange, sku, onSaved }) {
  const [form, setForm] = useState({
    nome_produto: "",
    linha: "",
    volume: "",
    unidade: "ml",
    status: "ativo",
    ean13: "",
    dum14: "",
    prod_hora_manual: "",
  });
  const isEditing = !!sku?.id;

  useEffect(() => {
    setForm({
      nome_produto: sku?.nome_produto || "",
      linha: sku?.linha_produto || sku?.linha || "",
      volume: skuVolume(sku || ""),
      unidade: sku?.unidade || "ml",
      status: sku?.status || "ativo",
      ean13: sku?.ean13 || "",
      dum14: sku?.dum14 || "",
      prod_hora_manual: sku?.medias_producao?.meta_unh || "",
    });
  }, [sku, open]);

  const update = (field, value) => setForm((prev) => ({ ...prev, [field]: value }));

  const save = async () => {
    if (!isEditing) {
      toast.info("Novo SKU deve nascer do P&D concluido/aprovado. Esta tela replica o cadastro e evita produto sem ficha tecnica.");
      onOpenChange(false);
      return;
    }
    try {
      await api.put(`/crm/skus/${sku.id}`, {
        nome_produto: form.nome_produto,
        status: form.status,
      });
      if (form.prod_hora_manual !== "") {
        await api.post(`/crm/skus/${sku.id}/meta`, { meta_unh: Number(form.prod_hora_manual) || 0 });
      }
      toast.success("Produto atualizado");
      onOpenChange(false);
      onSaved?.();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Erro ao atualizar produto");
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="pcp-theme max-w-3xl border-white/10 bg-[#1f1f22] p-0 text-white">
        <DialogHeader className="rounded-t-2xl bg-[#098f2e] px-5 py-4">
          <DialogTitle className="text-base font-black">{isEditing ? "Editar Produto" : "Novo Produto"}</DialogTitle>
        </DialogHeader>
        <div className="max-h-[64vh] overflow-y-auto px-5 py-4">
          <div className="grid grid-cols-1 gap-4 md:grid-cols-12">
            <div className="md:col-span-12">
              <Label className="text-xs text-zinc-400">Descricao do Item *</Label>
              <Input value={form.nome_produto} onChange={(e) => update("nome_produto", e.target.value)} placeholder="Nome completo do produto" className="mt-1 border-white/10 bg-zinc-100 text-black" />
            </div>
            <div className="md:col-span-6">
              <Label className="text-xs text-zinc-400">Linha do Produto</Label>
              <Input value={form.linha} onChange={(e) => update("linha", e.target.value)} placeholder="Ex: ARABY'S" className="mt-1 border-white/10 bg-[#1f1f22] text-white" />
            </div>
            <div className="md:col-span-4">
              <Label className="text-xs text-zinc-400">Volume</Label>
              <Input value={form.volume} onChange={(e) => update("volume", e.target.value)} placeholder="Ex: 200" className="mt-1 border-white/10 bg-zinc-100 text-black" />
            </div>
            <div className="md:col-span-2">
              <Label className="text-xs text-zinc-400">U.M.</Label>
              <Select value={form.unidade} onValueChange={(v) => update("unidade", v)}>
                <SelectTrigger className="mt-1 border-white/10 bg-[#1f1f22] text-white"><SelectValue /></SelectTrigger>
                <SelectContent><SelectItem value="ml">ml</SelectItem><SelectItem value="g">g</SelectItem><SelectItem value="un">un</SelectItem></SelectContent>
              </Select>
            </div>
            <div className="md:col-span-6">
              <Label className="text-xs text-zinc-400">Status</Label>
              <Select value={form.status} onValueChange={(v) => update("status", v)}>
                <SelectTrigger className="mt-1 border-white/10 bg-zinc-100 text-black"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="ativo">Ativo</SelectItem>
                  <SelectItem value="suspenso">Suspenso</SelectItem>
                  <SelectItem value="descontinuado">Descontinuado</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>

          <div className="mt-6 border-t border-white/10 pt-4">
            <p className="mb-3 text-xs font-black uppercase tracking-wide text-zinc-500">Codigos de Barras</p>
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
              <div><Label className="text-xs text-zinc-400">EAN-13</Label><Input value={form.ean13} onChange={(e) => update("ean13", e.target.value)} placeholder="13 digitos" className="mt-1 border-white/10 bg-[#1f1f22] text-white" /></div>
              <div><Label className="text-xs text-zinc-400">DUM-14</Label><Input value={form.dum14} onChange={(e) => update("dum14", e.target.value)} placeholder="14 digitos" className="mt-1 border-white/10 bg-[#1f1f22] text-white" /></div>
            </div>
          </div>

          <div className="mt-6 border-t border-white/10 pt-4">
            <p className="mb-3 text-xs font-black uppercase tracking-wide text-zinc-500">Historico de Producao</p>
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
              <div><Label className="text-xs text-zinc-400">Prod/hora (referencia manual)</Label><Input value={form.prod_hora_manual} onChange={(e) => update("prod_hora_manual", e.target.value)} placeholder="Ex: 1200" className="mt-1 border-white/10 bg-[#1f1f22] text-white" /></div>
              <div><Label className="text-xs text-zinc-400">Prod/hora (calculado dos apontamentos)</Label><Input disabled value={sku?.medias_producao?.media_geral_unh ? `${fmt(Math.round(sku.medias_producao.media_geral_unh))} un/h` : "-"} className="mt-1 border-white/10 bg-zinc-100 text-black" /></div>
            </div>
          </div>
        </div>
        <DialogFooter className="rounded-b-2xl bg-zinc-100 px-5 py-4">
          <Button variant="outline" className="border-zinc-300 bg-[#1f1f22] text-white hover:bg-zinc-900" onClick={() => onOpenChange(false)}>Cancelar</Button>
          <Button className="bg-[#00bf20] font-black hover:bg-[#00a91c]" onClick={save}>{isEditing ? "Salvar Produto" : "Salvar Produto"}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function ProductsPage({ data }) {
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("all");
  const [category, setCategory] = useState("all");
  const [client, setClient] = useState("all");
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingSku, setEditingSku] = useState(null);

  const categories = useMemo(() => Array.from(new Set(data.skus.map((s) => s.categoria || s.cat3).filter(Boolean))).sort(), [data.skus]);
  const clients = useMemo(() => Array.from(new Set(data.skus.map(skuClientName).filter((v) => v && v !== "-"))).sort(), [data.skus]);

  const filtered = useMemo(() => data.skus.filter((sku) => {
    const hay = `${sku.codigo_interno || ""} ${sku.nome_produto || ""} ${skuClientName(sku)} ${sku.categoria || ""}`.toLowerCase();
    if (search && !hay.includes(search.toLowerCase())) return false;
    if (status !== "all" && sku.status !== status) return false;
    if (category !== "all" && (sku.categoria || sku.cat3) !== category) return false;
    if (client !== "all" && skuClientName(sku) !== client) return false;
    return true;
  }), [data.skus, search, status, category, client]);

  const active = data.skus.filter((sku) => sku.status === "ativo").length;
  const inactive = data.skus.length - active;

  const openNew = () => {
    setEditingSku(null);
    setDialogOpen(true);
  };
  const openEdit = (sku) => {
    setEditingSku(sku);
    setDialogOpen(true);
  };

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 gap-2">
        <div className="relative">
          <Search className="absolute left-3 top-3 h-4 w-4 text-zinc-500" />
          <Input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Buscar por SKU, descricao, cliente..." className="h-10 border-white/10 bg-[#1f1f22] pl-9 text-white" />
        </div>
        <Select value={status} onValueChange={setStatus}>
          <SelectTrigger className="border-white/10 bg-[#1f1f22] text-white"><SelectValue /></SelectTrigger>
          <SelectContent><SelectItem value="all">Todos</SelectItem><SelectItem value="ativo">Ativos</SelectItem><SelectItem value="suspenso">Suspensos</SelectItem><SelectItem value="descontinuado">Descontinuados</SelectItem></SelectContent>
        </Select>
        <Select value={category} onValueChange={setCategory}>
          <SelectTrigger className="border-white/10 bg-[#1f1f22] text-white"><SelectValue placeholder="Todas categorias" /></SelectTrigger>
          <SelectContent><SelectItem value="all">Todas categorias</SelectItem>{categories.map((cat) => <SelectItem key={cat} value={cat}>{cat}</SelectItem>)}</SelectContent>
        </Select>
        <Select value={client} onValueChange={setClient}>
          <SelectTrigger className="border-white/10 bg-[#1f1f22] text-white"><SelectValue placeholder="Todos clientes" /></SelectTrigger>
          <SelectContent><SelectItem value="all">Todos clientes</SelectItem>{clients.map((name) => <SelectItem key={name} value={name}>{name}</SelectItem>)}</SelectContent>
        </Select>
      </div>

      <div className="flex flex-wrap gap-2">
        <Button className="bg-[#00bf20] font-black hover:bg-[#00a91c]" onClick={openNew}>+ Novo Produto</Button>
        <Button variant="outline" className="border-white/20 bg-[#2b2b2e] text-white hover:bg-zinc-800" onClick={data.load}><RefreshCw className="mr-2 h-4 w-4" /> Prod/hora</Button>
      </div>

      <div className="grid grid-cols-1 gap-3 md:grid-cols-4">
        <Stat value={fmt(data.skus.length)} label="Total" />
        <Stat value={fmt(active)} label="Ativos" />
        <Stat value={fmt(inactive)} label="Inativos" />
        <Stat value={fmt(categories.length)} label="Categorias" />
      </div>

      <DarkCard className="p-0">
        <div className="border-b border-white/10 px-4 py-4 text-xs font-black uppercase tracking-wide text-zinc-500">Produtos ({filtered.length} exibidos)</div>
        <div className="mx-4 my-3 grid gap-3 rounded-lg bg-emerald-50 px-4 py-3 text-sm text-emerald-800 md:grid-cols-[1fr_auto_1.4fr]">
          <span>O cadastro de produtos agora sincroniza automaticamente da planilha</span>
          <b>Criador de OPs vF.xlsm</b>
          <span>Para corrigir um produto, edite pelo fluxo aprovado ou ajuste o SKU existente aqui.</span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[1060px] text-sm">
            <thead className="bg-zinc-100 text-left text-[11px] uppercase tracking-wide text-zinc-500">
              <tr>
                {["SKU", "Descricao", "Cliente", "Categoria", "Subcategoria", "Viscosidade", "Volume", "Un/h", "Acoes"].map((h) => <th key={h} className="p-3">{h}</th>)}
              </tr>
            </thead>
            <tbody>
              {filtered.map((sku) => (
                <tr key={sku.id || sku.codigo_interno} className="border-b border-white/10">
                  <td className="p-3 font-mono text-xs text-zinc-400">{valueText(sku.codigo_interno)}</td>
                  <td className="p-3 font-black">{valueText(sku.nome_produto)}</td>
                  <td className="p-3">{skuClientName(sku)}</td>
                  <td className="p-3">{sku.categoria ? <Badge className="bg-blue-100 text-blue-700">{sku.categoria}</Badge> : <Badge className="bg-zinc-100 text-zinc-600">-</Badge>}</td>
                  <td className="p-3 text-zinc-500">{valueText(sku.subcategoria)}</td>
                  <td className="p-3">{sku.viscosidade ? <Badge className="bg-orange-100 text-orange-700">{sku.viscosidade}</Badge> : <Badge className="bg-orange-50 text-orange-700">-</Badge>}</td>
                  <td className="p-3 font-bold">{skuVolume(sku) || "-"}</td>
                  <td className="p-3">{sku.medias_producao?.media_geral_unh ? `${fmt(Math.round(sku.medias_producao.media_geral_unh))}` : "-"}</td>
                  <td className="p-3">
                    <div className="flex items-center gap-2">
                      <Badge className={statusClass(sku.status)}>{sku.status || "sem status"}</Badge>
                      <Button size="icon" variant="outline" className="h-8 w-8 border-white/20 bg-transparent text-white" onClick={() => openEdit(sku)} title="Editar produto">
                        <Pencil className="h-4 w-4" />
                      </Button>
                    </div>
                  </td>
                </tr>
              ))}
              {filtered.length === 0 && <tr><td colSpan={9} className="p-8 text-center text-zinc-500">Nenhum produto encontrado.</td></tr>}
            </tbody>
          </table>
        </div>
      </DarkCard>

      <ProductDialog open={dialogOpen} onOpenChange={setDialogOpen} sku={editingSku} onSaved={data.load} />
    </div>
  );
}

const MATRIX_COLUMNS = [
  { label: "ART", match: ["arte", "aprov"] },
  { label: "ANV", match: ["anvisa", "notifica"] },
  { label: "ROT", match: ["rot", "grava"] },
  { label: "FRA", match: ["frasco", "pote"] },
  { label: "TAM", match: ["tampa", "sobretampa"] },
  { label: "CAR", match: ["cartucho"] },
  { label: "VAL", match: ["valv", "vÃ¡lv", "válv"] },
  { label: "CEL", match: ["celofane", "sleeve"] },
  { label: "DIS", match: ["display"] },
  { label: "CAI", match: ["caixa"] },
  { label: "ESS", match: ["ess", "fragr"] },
  { label: "MP", match: ["mater", "prima"] },
];

function norm(value) {
  return String(value || "").toLowerCase();
}

function checklistFor(order, column) {
  return (order.checklist_insumos || []).find((item) => column.match.some((needle) => norm(item.categoria).includes(needle)));
}

function statusMark(item) {
  if (!item || !item.ativo) return { text: "-", className: "text-zinc-500" };
  if (["recebido", "confirmado"].includes(item.status)) return { text: "✓", className: "text-white" };
  if (item.status === "em_andamento") return { text: "!", className: "text-amber-400" };
  return { text: "?", className: "text-red-500" };
}

function orderOk(order) {
  const active = (order.checklist_insumos || []).filter((item) => item.ativo);
  return active.length > 0 && active.every((item) => ["recebido", "confirmado"].includes(item.status));
}

function MatrixPage({ data }) {
  const [search, setSearch] = useState("");
  const [showClosed, setShowClosed] = useState(false);
  const [tab, setTab] = useState("matriz");
  const [selectedId, setSelectedId] = useState("");
  const [receiving, setReceiving] = useState(false);

  const filteredOrders = useMemo(() => data.orders.filter((order) => {
    if (!showClosed && ["concluido", "cancelado"].includes(order.status)) return false;
    const hay = `${order.numero_pedido || ""} ${order.cliente?.nome || ""} ${(order.items || []).map((i) => `${i.item} ${i.codigo_kuryos}`).join(" ")}`.toLowerCase();
    return !search || hay.includes(search.toLowerCase());
  }), [data.orders, search, showClosed]);

  const selectedOrder = filteredOrders.find((order) => order.id === selectedId) || filteredOrders[0];

  const receiveBatch = async () => {
    const targets = filteredOrders.filter((order) => {
      if (["concluido", "cancelado"].includes(order.status)) return false;
      return (order.checklist_insumos || []).some((item) => item.ativo && !["recebido", "confirmado"].includes(item.status));
    });
    if (!targets.length) {
      toast.info("Nao ha insumos pendentes nos pedidos filtrados.");
      return;
    }
    if (!window.confirm(`Confirmar recebimento dos insumos pendentes em ${targets.length} pedido(s) filtrado(s)?`)) return;
    setReceiving(true);
    try {
      await Promise.all(targets.map((order) => {
        const checklist = (order.checklist_insumos || []).map((item) => {
          if (!item.ativo || ["recebido", "confirmado"].includes(item.status)) return item;
          const obs = item.observacoes ? `${item.observacoes}\nRecebido em lote pelo PCP.` : "Recebido em lote pelo PCP.";
          return { ...item, status: "recebido", observacoes: obs };
        });
        return api.put(`/orders/${order.id}`, { checklist_insumos: checklist });
      }));
      toast.success(`${targets.length} pedido(s) atualizados no recebimento em lote.`);
      await data.load();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Nao foi possivel registrar o recebimento em lote.");
    } finally {
      setReceiving(false);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex w-full overflow-x-auto rounded-2xl bg-[#1f1f22] p-1 md:inline-flex md:w-auto">
        <button onClick={() => setTab("matriz")} className={`rounded-xl px-6 py-2 text-sm font-black ${tab === "matriz" ? "bg-[#6485f2] text-white" : "text-zinc-500"}`}><FileSpreadsheet className="mr-2 inline h-4 w-4" />Visao Geral (Matriz)</button>
        <button onClick={() => setTab("detalhes")} className={`rounded-xl px-6 py-2 text-sm font-black ${tab === "detalhes" ? "bg-[#6485f2] text-white" : "text-zinc-500"}`}><Search className="mr-2 inline h-4 w-4" />Detalhes do Pedido</button>
      </div>

      <DarkCard>
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div className="relative w-full lg:max-w-sm">
            <Search className="absolute left-3 top-3 h-4 w-4 text-zinc-500" />
            <Input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Filtrar por ID ou Produto..." className="border-white/10 bg-[#1f1f22] pl-9 text-white" />
          </div>
          <label className="flex min-h-9 cursor-pointer items-center gap-2 rounded-md px-1 text-sm font-bold text-zinc-400">
            <input type="checkbox" checked={showClosed} onChange={(e) => setShowClosed(e.target.checked)} className="h-7 w-7 accent-[#6485f2]" />
            Mostrar concluidos/encerrados
          </label>
          <Button className="bg-[#6485f2] font-black hover:bg-[#7593ff]" disabled={receiving} onClick={receiveBatch}>
            {receiving ? "Recebendo..." : "Recebimento em Lote"}
          </Button>
        </div>
      </DarkCard>

      {tab === "matriz" ? (
        <DarkCard className="p-0">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[1080px] text-sm">
              <thead className="bg-zinc-100 text-[11px] uppercase tracking-wide text-zinc-500">
                <tr>
                  <th className="w-[345px] p-3 text-left">Produto / SKU</th>
                  {MATRIX_COLUMNS.map((col) => <th key={col.label} className="p-3 text-center">{col.label}</th>)}
                  <th className="bg-emerald-50 p-3 text-center">OK</th>
                </tr>
              </thead>
              <tbody>
                {filteredOrders.map((order) => (
                  <FragmentRows key={order.id} order={order} onSelect={() => { setSelectedId(order.id); setTab("detalhes"); }} />
                ))}
                {filteredOrders.length === 0 && <tr><td colSpan={14} className="p-8 text-center text-zinc-500">Nenhum pedido encontrado para a matriz.</td></tr>}
              </tbody>
            </table>
          </div>
        </DarkCard>
      ) : (
        <DarkCard>
          {selectedOrder ? (
            <div className="grid grid-cols-1 gap-5 lg:grid-cols-[280px_1fr]">
              <div className="space-y-2">
                {filteredOrders.map((order) => (
                  <button key={order.id} onClick={() => setSelectedId(order.id)} className={`w-full rounded-lg border px-3 py-2 text-left text-sm ${selectedOrder.id === order.id ? "border-[#6485f2] bg-[#6485f2]/15" : "border-white/10 bg-black"}`}>
                    <p className="font-black">Pedido #{order.numero_pedido || order.id}</p>
                    <p className="truncate text-xs text-zinc-500">{order.cliente?.nome || "Cliente"} - {(order.items || []).length} itens</p>
                  </button>
                ))}
              </div>
              <div>
                <h2 className="text-xl font-black">Pedido #{selectedOrder.numero_pedido || selectedOrder.id}</h2>
                <p className="mb-4 text-sm text-zinc-500">{selectedOrder.cliente?.nome || "Cliente"} - status {selectedOrder.status || "-"}</p>
                <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                  {(selectedOrder.checklist_insumos || []).map((item) => {
                    const ok = item.ativo && ["recebido", "confirmado"].includes(item.status);
                    return (
                      <div key={item.categoria} className="rounded-lg border border-white/10 bg-black p-3">
                        <div className="flex items-center justify-between gap-3">
                          <p className="font-black">{item.categoria}</p>
                          {ok ? <CheckCircle2 className="h-5 w-5 text-emerald-400" /> : item.ativo ? <AlertTriangle className="h-5 w-5 text-red-400" /> : <span className="text-zinc-600">-</span>}
                        </div>
                        <p className="mt-1 text-xs text-zinc-500">Origem: {item.origem || "-"} | Status: {item.status || "-"}</p>
                        {item.observacoes && <p className="mt-2 text-xs text-zinc-300">{item.observacoes}</p>}
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>
          ) : (
            <p className="p-8 text-center text-zinc-500">Selecione um pedido.</p>
          )}
        </DarkCard>
      )}
    </div>
  );
}

function FragmentRows({ order, onSelect }) {
  const items = order.items?.length ? order.items : [{ item: order.project_name || "Pedido sem item", codigo_kuryos: "-" }];
  const ok = orderOk(order);
  return (
    <>
      <tr className="cursor-pointer bg-zinc-100 text-[#6485f2]" onClick={onSelect}>
        <td className="p-3 text-xs font-black" colSpan={14}>Pedido #{order.numero_pedido || order.id} - {order.cliente?.nome || "Cliente"} <span className="ml-2 text-zinc-500">({items.length} itens)</span></td>
      </tr>
      {items.map((item, idx) => (
        <tr key={`${order.id}-${idx}`} className={`${idx % 2 === 0 ? "bg-zinc-50 text-zinc-400" : "bg-[#1f1f22] text-white"} border-b border-zinc-700`}>
          <td className="p-3 font-black">
            {item.item || "Produto"}
            <p className="mt-1 text-[10px] font-normal text-zinc-500">SKU: {item.codigo_kuryos || "-"} - {fmt(item.qtd || item.qtd_planejada || 0)} un.</p>
          </td>
          {MATRIX_COLUMNS.map((col) => {
            const mark = statusMark(checklistFor(order, col));
            return <td key={col.label} className={`p-3 text-center text-xl font-black ${mark.className}`}>{mark.text}</td>;
          })}
          <td className="bg-emerald-50 p-3 text-center text-xl font-black text-red-500">{ok ? "✓" : "?"}</td>
        </tr>
      ))}
    </>
  );
}

export default function PCPClonePage({ mode }) {
  const data = usePcpData();
  if (data.loading) {
    return (
      <Shell>
        <div className="rounded-3xl bg-[#1f1f22] p-12 text-center text-zinc-400">Carregando...</div>
      </Shell>
    );
  }
  return (
    <Shell>
      {mode === "planejamento" && <PlanningPage data={data} />}
      {mode === "historico" && <HistorySalesPage data={data} />}
      {mode === "horizonte" && <HorizonPage data={data} />}
      {mode === "controle" && <ControlOpsPage data={data} />}
      {mode === "emitir-op" && <EmitOPPage data={data} />}
      {mode === "produtos" && <ProductsPage data={data} />}
      {mode === "matriz" && <MatrixPage data={data} />}
    </Shell>
  );
}
