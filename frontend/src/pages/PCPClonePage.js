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
  AlertTriangle, CheckCircle2, FileSpreadsheet, FileUp, Pencil, RefreshCw, Search, Wrench,
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
  const initialTab = ["grade", "agenda", "config"].includes(tabParam) ? tabParam : "grade";
  const [tab, setTab] = useState(initialTab);
  const [search, setSearch] = useState("");
  const [schedulingId, setSchedulingId] = useState("");
  const [importing, setImporting] = useState(false);
  const weekStart = startOfWeek(data.day);
  const weekEnd = addDays(weekStart, 6);
  const activeOps = data.ops.filter(op => ["aberta", "em_processo", "pausada"].includes(op.status));
  const activeLines = data.linhas.filter(linha => linha.status !== "inativa");
  const totalPlanejado = data.slots.reduce((s, slot) => s + Number(slot.qtd_planejada || 0), 0);
  const diasProgramados = new Set(data.slots.map(slot => slot.data || slot.data_inicio).filter(Boolean)).size;

  useEffect(() => {
    const current = new URLSearchParams(location.search).get("tab");
    if (["grade", "agenda", "config"].includes(current)) setTab(current);
  }, [location.search]);

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
        data: weekStart,
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

  const importSchedule = async (file) => {
    if (!file) return;
    const form = new FormData();
    form.append("file", file);
    setImporting(true);
    try {
      const { data: result } = await api.post("/pcp/importar-programacao", form);
      toast.success(`${result.importados || 0} slots importados. ${result.ignorados || 0} ignorados.`);
      await data.load();
      setTab("grade");
      navigate("/pcp/planejamento", { replace: true });
    } catch (err) {
      toast.error(err.response?.data?.detail || "Nao foi possivel importar a programacao.");
    } finally {
      setImporting(false);
    }
  };

  return (
    <>
      <div className="mb-4 flex w-full gap-1 overflow-x-auto rounded-2xl bg-[#1f1f22] p-1 md:inline-flex md:w-auto">
        {[
          ["grade", "Grade Semanal"],
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
                        <Badge className="bg-amber-100 text-amber-700">{op.status === "em_processo" ? "Producao Parcial" : "Programado"}</Badge>
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
          <DarkCard className="border-l-4 border-l-[#6485f2]">
            <h2 className="mb-4 text-base font-black">Importar Programacao Semanal (Previsao de Envase)</h2>
            <p className="mb-4 text-sm text-zinc-500">Selecione ou arraste a planilha semanal para importar todos os slots planejados.</p>
            <label
              className={`flex min-h-[140px] cursor-pointer items-center justify-center rounded-2xl border border-dashed border-zinc-600 transition hover:border-[#6485f2] hover:bg-[#6485f2]/10 ${importing ? "pointer-events-none opacity-60" : ""}`}
              onDragOver={(event) => event.preventDefault()}
              onDrop={(event) => {
                event.preventDefault();
                importSchedule(event.dataTransfer.files?.[0]);
              }}
            >
              <input
                type="file"
                accept=".xlsx,.xlsm"
                className="hidden"
                disabled={importing}
                onChange={(event) => {
                  importSchedule(event.target.files?.[0]);
                  event.target.value = "";
                }}
              />
              <div className="text-center">
                <FileUp className="mx-auto h-9 w-9 text-yellow-400" />
                <p className="mt-3 font-black">{importing ? "Importando planilha..." : "Clique ou arraste o arquivo da planilha aqui"}</p>
                <p className="mt-1 text-xs text-zinc-500">Aceita: .xlsm e .xlsx - aba Previsao Envase</p>
              </div>
            </label>
          </DarkCard>
          <DarkCard>
            <h2 className="mb-4 text-base font-black">Horas de Producao</h2>
            <p className="text-sm text-zinc-300">As horas de producao vem direto do horario de turno. Ajuste em Configuracoes - Horarios dos Turnos e Apontamento.</p>
          </DarkCard>
          <DarkCard>
            <h2 className="mb-4 text-base font-black">Dias de Trabalho</h2>
            <div className="flex flex-wrap gap-2">
              {["Segunda", "Terca", "Quarta", "Quinta", "Sexta", "Sabado", "Domingo"].map((d, i) => (
                <button key={d} className={`rounded-lg px-5 py-3 font-black ${i < 5 ? "bg-emerald-100 text-emerald-800" : "bg-black text-zinc-400 border border-zinc-600"}`}>{d}</button>
              ))}
            </div>
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
    </>
  );
}

function HorizonPage({ data }) {
  const [weeks, setWeeks] = useState(10);
  const backlog = data.ops.filter(op => ["aberta", "em_processo", "pausada"].includes(op.status));
  return (
    <div className="space-y-4">
      <DarkCard>
        <div className="flex flex-col gap-3 md:flex-row md:items-center">
          <span className="text-sm font-bold text-zinc-500">Horizonte:</span>
          <Button size="icon" className="h-9 w-9 min-w-9 bg-black" onClick={() => setWeeks(w => Math.max(1, w - 1))}>-</Button>
          <span className="font-black">{weeks} semanas</span>
          <Button size="icon" className="h-9 w-9 min-w-9 bg-black" onClick={() => setWeeks(w => w + 1)}>+</Button>
          <div className="flex flex-wrap gap-4 text-xs text-zinc-500 md:ml-auto">
            <span><b className="text-blue-300">■</b> Linha propria do pedido</span>
            <span><b className="text-violet-300">■</b> Linha sugerida automaticamente</span>
            <span><b className="text-green-500">●</b> Insumo OK</span>
            <span><b className="text-yellow-500">●</b> Insumo pendente</span>
          </div>
        </div>
      </DarkCard>
      <DarkCard>
        <h2 className="mb-5 text-base font-black">Capacidade por Linha</h2>
        <div className="space-y-5">
          {(data.linhas.length ? data.linhas : [{ nome: "Linha 1" }, { nome: "Linha 2" }, { nome: "Linha 3" }]).slice(0, 3).map((linha, idx) => (
            <div key={linha.id || idx} className="grid grid-cols-1 gap-2 md:grid-cols-[90px_1fr_140px] md:items-center md:gap-4">
              <span className="font-black">{linha.nome}</span>
              <div className="h-1 overflow-hidden rounded-full bg-zinc-300"><div className="h-full bg-[#6485f2]" style={{ width: `${idx === 1 ? 100 : 92}%` }} /></div>
              <span className="text-right text-xs text-zinc-500">ocupada ate 16/10</span>
            </div>
          ))}
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
                <span className="text-xs text-zinc-500">semana de 17/08</span>
                <Button className="bg-[#6485f2] font-black hover:bg-[#7593ff]">Congelar</Button>
              </div>
            );
          })}
        </div>
      </DarkCard>
    </div>
  );
}

function ControlOpsPage({ data }) {
  const navigate = useNavigate();
  const [savingOp, setSavingOp] = useState("");
  const [recalculating, setRecalculating] = useState(false);
  const activeOps = data.ops.filter(op => ["aberta", "em_processo", "pausada"].includes(op.status));
  const updateOp = async (op, payload) => {
    setSavingOp(op.id);
    try {
      await api.put(`/ops/${op.id}`, payload);
      toast.success("OP atualizada.");
      await data.load();
    } catch (err) {
      toast.error(err.response?.data?.detail?.message || err.response?.data?.detail || "Nao foi possivel atualizar a OP.");
    } finally {
      setSavingOp("");
    }
  };
  const recalculateStatus = async () => {
    setRecalculating(true);
    try {
      const { data: result } = await api.post("/pcp/recalcular-status");
      toast.success(`${result.ops_sincronizadas || 0} OPs sincronizadas. ${result.slots_bloqueados || 0} bloqueios tecnicos.`);
      await data.load();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Nao foi possivel recalcular os status.");
    } finally {
      setRecalculating(false);
    }
  };
  return (
    <div className="space-y-4">
      <div className="flex flex-col items-start justify-between gap-4 md:flex-row">
        <div>
          <h1 className="text-3xl font-black">Controle de OPs Ativas</h1>
          <p className="mt-1 text-sm text-zinc-500">Acompanhe o progresso fisico e gerencie as OPs ativas em producao</p>
        </div>
        <Button className="w-full bg-[#6485f2] font-black hover:bg-[#7593ff] md:w-auto" disabled={recalculating} onClick={recalculateStatus}>
          {recalculating ? "Recalculando..." : "Recalcular Status de Todas as OPs / Lotes"}
        </Button>
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
                  <tr key={op.id} className="border-b border-white/20">
                    <td className="p-4 font-black">{op.numero_op}</td>
                    <td className="p-4">{op.cliente_nome || "-"}</td>
                    <td className="p-4 font-black">{item.item || op.project_name || "-"}<p className="text-xs font-normal text-zinc-500">SKU: {item.codigo_kuryos || "-"}</p></td>
                    <td className="p-4">
                      <Select
                        value={op.linha_id || "none"}
                        disabled={savingOp === op.id}
                        onValueChange={(linhaId) => {
                          const linha = data.linhas.find(l => l.id === linhaId);
                          updateOp(op, {
                            linha_id: linhaId === "none" ? "" : linhaId,
                            linha_nome: linha?.nome || "",
                          });
                        }}
                      >
                        <SelectTrigger className="w-32 border-white/10 bg-[#1f1f22] text-white"><SelectValue /></SelectTrigger>
                        <SelectContent><SelectItem value="none">Sem linha</SelectItem>{data.linhas.map(l => <SelectItem key={l.id} value={l.id}>{l.nome}</SelectItem>)}</SelectContent>
                      </Select>
                    </td>
                    <td className="p-4"><Badge className="bg-violet-100 text-violet-700">#{op.numero_pedido || "-"}</Badge></td>
                    <td className="p-4">
                      <div className="mb-1 flex justify-between text-xs font-black"><span>{fmt(done)} / {fmt(planned)} un</span><span>{progress}%</span></div>
                      <div className="h-2 overflow-hidden rounded-full bg-zinc-300"><div className="h-full bg-[#00bf20]" style={{ width: `${progress}%` }} /></div>
                    </td>
                    <td className="p-4">
                      <Select value={op.status} disabled={savingOp === op.id} onValueChange={(status) => updateOp(op, { status })}>
                        <SelectTrigger className="w-36 border-white/10 bg-[#1f1f22] text-white"><SelectValue /></SelectTrigger>
                        <SelectContent>{["aberta", "em_processo", "pausada", "concluida"].map(s => <SelectItem key={s} value={s}>{s}</SelectItem>)}</SelectContent>
                      </Select>
                    </td>
                    <td className="p-4"><Button variant="outline" size="icon" className="border-white/20 bg-transparent text-red-300" onClick={() => navigate(`/ops/${op.id}`)}><Wrench className="h-4 w-4" /></Button></td>
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
      {mode === "horizonte" && <HorizonPage data={data} />}
      {mode === "controle" && <ControlOpsPage data={data} />}
      {mode === "produtos" && <ProductsPage data={data} />}
      {mode === "matriz" && <MatrixPage data={data} />}
    </Shell>
  );
}
