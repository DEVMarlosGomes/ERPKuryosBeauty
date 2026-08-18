import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import api from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  AlertTriangle, Calendar, ChevronLeft, ChevronRight,
} from "lucide-react";
import { toast } from "sonner";

const WEEK_DAYS = ["domingo", "segunda-feira", "terca-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sabado"];
const MONTHS = ["janeiro", "fevereiro", "marco", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"];

function toYMD(date) {
  return date.toISOString().slice(0, 10);
}

function parseYMD(ymd) {
  const [y, m, d] = ymd.split("-").map(Number);
  return new Date(y, m - 1, d);
}

function formatLongDate(ymd) {
  const d = parseYMD(ymd);
  return `${WEEK_DAYS[d.getDay()]}, ${d.getDate()} de ${MONTHS[d.getMonth()]} de ${d.getFullYear()}`;
}

function formatBR(ymd) {
  const [y, m, d] = ymd.split("-");
  return `${d}/${m}/${y}`;
}

function startOfWeek(ymd) {
  const d = parseYMD(ymd);
  const day = d.getDay();
  d.setDate(d.getDate() - (day === 0 ? 6 : day - 1));
  return toYMD(d);
}

function addDays(ymd, days) {
  const d = parseYMD(ymd);
  d.setDate(d.getDate() + days);
  return toYMD(d);
}

function fmt(n) {
  return Number(n || 0).toLocaleString("pt-BR");
}

function LineCard({ linha, slot }) {
  const planejado = Number(slot?.qtd_planejada || 0);
  const produzido = Number(slot?.qtd_produzida || 0);
  const pct = planejado > 0 ? Math.min(Math.round((produzido / planejado) * 100), 100) : 0;
  const operando = slot?.status === "em_execucao";

  return (
    <div className="min-h-[116px] rounded-2xl border border-white/5 bg-[#1f1f22] p-4 shadow-[0_14px_28px_rgba(0,0,0,0.35)]">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-sm font-bold text-white">{linha?.nome || "Linha"}</h3>
        <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[10px] font-black ${operando ? "bg-[#063d16] text-[#04c821]" : "bg-white/5 text-zinc-400"}`}>
          <span className={`h-2.5 w-2.5 rounded-full ${operando ? "bg-[#04c821]" : "bg-zinc-500"}`} />
          {operando ? "OPERANDO" : "SEM OP"}
        </span>
      </div>
      <p className="mt-3 h-4 truncate text-xs font-black text-white">
        {slot ? `${slot.op_numero || "OP"} - ${slot.produto_nome || slot.op_nome || "Produto"}` : "Sem OP alocada"}
      </p>
      <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-zinc-700">
        <div className="h-full rounded-full bg-[#00bf20]" style={{ width: `${pct}%` }} />
      </div>
      <div className="mt-2 flex items-center justify-between text-[11px] text-zinc-400">
        <span>{fmt(produzido)} / {fmt(planejado)} un.</span>
        <span>{pct}%</span>
      </div>
    </div>
  );
}

function GoalBar({ title, subtitle, produced, target, tone = "blue" }) {
  const pct = target > 0 ? Math.min(Math.round((produced / target) * 100), 100) : 0;
  const bar = tone === "orange" ? "bg-[#ffb000]" : "bg-blue-500";
  const number = tone === "orange" ? "text-[#ff9800]" : "text-blue-500";

  return (
    <div className="rounded-lg bg-zinc-100 px-4 py-3 text-zinc-900">
      <div className="flex items-start justify-between gap-4">
        <div>
          {title && <p className="text-[11px] font-black uppercase tracking-wide text-zinc-400">{title}</p>}
          <h4 className="mt-1 text-sm font-black text-zinc-50 mix-blend-difference">{subtitle || "-"}</h4>
        </div>
        <div className="text-right">
          <p className={`text-2xl font-black leading-none ${number}`}>{pct}%</p>
          <p className="text-[10px] text-zinc-500">concluido</p>
        </div>
      </div>
      <div className="mt-3 h-2 overflow-hidden rounded-full bg-zinc-300">
        <div className={`h-full rounded-full ${bar}`} style={{ width: `${pct}%` }} />
      </div>
      <div className="mt-2 grid grid-cols-3 text-[11px] text-zinc-500">
        <span>Produzido: {fmt(produced)} un</span>
        <span className="text-center">Meta: {fmt(target)} un</span>
        <span className="text-right">Saldo: {fmt(Math.max(target - produced, 0))} un</span>
      </div>
    </div>
  );
}

function MetricCard({ value, label, accent }) {
  return (
    <div className="relative overflow-hidden rounded-2xl bg-[#1f1f22] p-5">
      <span className={`absolute inset-x-0 top-0 h-0.5 ${accent}`} />
      <p className="text-3xl font-black leading-none text-white">{value}</p>
      <p className="mt-2 text-sm font-bold text-zinc-500">{label}</p>
    </div>
  );
}

function LaunchesCard({ rows }) {
  return (
    <section className="rounded-3xl bg-[#1f1f22] p-5 md:p-6">
      <h2 className="mb-5 text-base font-black">Lancamentos por OP / Posto - Hoje</h2>
      <div>
        {rows.slice(0, 6).map((row, idx) => (
          <div key={row.id || idx} className="grid grid-cols-[44px_1fr_auto] items-center gap-2 border-b border-white/10 py-3 last:border-0">
            <span className="font-mono text-sm font-black text-[#4c7dff]">{row.hora || "--:--"}</span>
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <Badge className={row.tipo === "perda" ? "bg-red-100 text-red-700" : "bg-emerald-100 text-emerald-700"}>
                  {row.tipo === "perda" ? "Parada" : "OP concluida"}
                </Badge>
                <p className="truncate text-sm font-black text-white">{row.produto || "Produto"}</p>
              </div>
              <p className="mt-0.5 truncate text-xs text-zinc-500">
                {row.linha || "Linha"} - {row.op_numero || "OP"} - {row.duracao_min ? `${row.duracao_min}min` : "apontamento registrado"}
              </p>
            </div>
            <span className={`font-mono text-sm font-black ${Number(row.qtd || 0) < 0 ? "text-red-300" : "text-white"}`}>
              {Number(row.qtd || 0) > 0 ? "+" : ""}{fmt(row.qtd)}
            </span>
          </div>
        ))}
        {rows.length === 0 && <p className="py-10 text-center text-sm text-zinc-500">Nenhuma producao registrada hoje.</p>}
      </div>
    </section>
  );
}

function TurnosCard({ hasActive }) {
  return (
    <section className="rounded-3xl bg-[#1f1f22] p-5 md:p-6">
      <h2 className="mb-8 text-base font-black">Turnos do Dia</h2>
      <div className="flex items-center justify-between gap-4">
        <div>
          <p className="font-black text-white">Padrao</p>
          <p className="mt-1 text-xs text-zinc-500">07:00 as 17:00</p>
        </div>
        <Badge className={hasActive ? "bg-yellow-500/15 text-yellow-400" : "bg-zinc-700 text-zinc-300"}>
          {hasActive ? "Em andamento" : "Sem execucao"}
        </Badge>
      </div>
    </section>
  );
}

function ProgressLine({ name, produced, target, muted }) {
  const pct = target > 0 ? Math.min(Math.round((produced / target) * 100), 100) : 0;
  return (
    <div className="border-b border-white/10 py-3 last:border-0">
      <div className="mb-2 flex items-center justify-between gap-3">
        <span className={`text-sm font-black ${muted ? "text-zinc-500" : "text-white"}`}>{name}</span>
        <div className="flex items-center gap-7 text-sm">
          <span className="font-mono text-zinc-400">{fmt(produced)} {target ? `/ ${fmt(target)}` : ""}</span>
          {target ? <span className="w-10 text-right font-black text-white">{pct}%</span> : <Badge className="bg-zinc-100 text-zinc-700">Sem Meta</Badge>}
        </div>
      </div>
      {target > 0 && (
        <div className="h-1.5 overflow-hidden rounded-full bg-zinc-300">
          <div className="h-full rounded-full bg-[#ffb000]" style={{ width: `${pct}%` }} />
        </div>
      )}
    </div>
  );
}

function ProgressPanel({ linhas, slotByLinha, producedByLine, metaDia, produzidoDia }) {
  const fallback = [{ nome: "Linha 1" }, { nome: "Linha 2" }, { nome: "Linha 3" }];
  return (
    <section className="rounded-3xl bg-[#1f1f22] p-5 md:p-6">
      <h2 className="mb-7 text-base font-black">Progresso Diario por Linha / Posto</h2>
      <ProgressLine name="Progresso do Envase (Meta Diaria)" produced={produzidoDia} target={metaDia} />
      <p className="mt-5 text-[11px] font-black uppercase tracking-widest text-zinc-500">Linhas de Envase</p>
      {(linhas.length ? linhas : fallback).map((linha, idx) => {
        const slot = slotByLinha[linha.id] || {};
        const target = Number(slot.qtd_planejada || (idx < 2 ? 6000 : 4000));
        return (
          <ProgressLine
            key={linha.id || idx}
            name={linha.nome || `Linha ${idx + 1}`}
            produced={Number(producedByLine[linha.id || linha.nome] || slot.qtd_produzida || 0)}
            target={target}
          />
        );
      })}
      <p className="mt-5 text-[11px] font-black uppercase tracking-widest text-zinc-500">Rotulagem & Outros Postos</p>
      {["Celofane", "Filme Shrink", "Corte de Pescante", "Remocao de Tampas", "Rotulagem Manual", "Montagem de Cartuchos"].map(name => (
        <ProgressLine key={name} name={name} produced={0} target={0} muted />
      ))}
    </section>
  );
}

function OrdersProgress({ orders }) {
  return (
    <section className="rounded-3xl bg-[#1f1f22] p-5 md:p-6">
      <h2 className="mb-5 text-base font-black">Acompanhamento de Pedidos</h2>
      <div className="space-y-3">
        {orders.slice(0, 8).map((order, idx) => {
          const pct = order.target > 0 ? Math.min(Math.round((order.produced / order.target) * 100), 100) : 0;
          return (
            <div key={order.numero || idx} className="border-b border-white/10 pb-3 last:border-0">
              <div className="flex items-start justify-between gap-4">
                <div className="min-w-0">
                  <Badge className="bg-violet-100 text-violet-700">#{order.numero || String(idx + 1).padStart(4, "0")}</Badge>
                  <p className="mt-1 truncate text-xs text-zinc-400">{order.produto || "Produto"}</p>
                  <p className="mt-1 text-[11px] text-zinc-400">
                    Meta: <b className="text-white">{fmt(order.target)}</b> - Produzido: <b className="text-white">{fmt(order.produced)}</b> - Saldo: <b className="text-white">{fmt(Math.max(order.target - order.produced, 0))}</b>
                  </p>
                </div>
                <span className="font-mono text-2xl font-black text-[#ff9800]">{pct}%</span>
              </div>
              <div className="mt-2 h-2 overflow-hidden rounded-full bg-zinc-300">
                <div className="h-full rounded-full bg-[#ffb000]" style={{ width: `${pct}%` }} />
              </div>
            </div>
          );
        })}
        {orders.length === 0 && <p className="py-10 text-center text-sm text-zinc-500">Nenhum pedido em acompanhamento.</p>}
      </div>
    </section>
  );
}

export default function PCPDailyDashboard() {
  const navigate = useNavigate();
  const [day, setDay] = useState(() => toYMD(new Date()));
  const [loading, setLoading] = useState(true);
  const [linhas, setLinhas] = useState([]);
  const [slots, setSlots] = useState([]);
  const [historicoDia, setHistoricoDia] = useState({ rows: [], kpis: {} });
  const [historicoSemana, setHistoricoSemana] = useState({ rows: [], kpis: {} });

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const weekStart = startOfWeek(day);
      const weekEnd = addDays(weekStart, 6);
      const [linhasRes, slotsRes, diaRes, semanaRes] = await Promise.all([
        api.get("/pcp/linhas"),
        api.get("/pcp/programacao", { params: { data_inicio: day, data_fim: day } }),
        api.get("/pcp/historico", { params: { data_inicio: day, data_fim: day } }),
        api.get("/pcp/historico", { params: { data_inicio: weekStart, data_fim: weekEnd } }),
      ]);
      setLinhas(linhasRes.data || []);
      setSlots(slotsRes.data || []);
      setHistoricoDia(diaRes.data || { rows: [], kpis: {} });
      setHistoricoSemana(semanaRes.data || { rows: [], kpis: {} });
    } catch {
      toast.error("Erro ao carregar dashboard diario do PCP");
    } finally {
      setLoading(false);
    }
  }, [day]);

  useEffect(() => { load(); }, [load]);

  const activeLinhas = useMemo(() => (linhas || []).filter(l => l.status !== "inativa").slice(0, 3), [linhas]);
  const slotByLinha = useMemo(() => {
    const map = {};
    for (const slot of slots || []) {
      const current = map[slot.linha_id];
      if (!current || slot.status === "em_execucao") map[slot.linha_id] = slot;
    }
    return map;
  }, [slots]);

  const metaDia = Math.max((slots || []).reduce((s, slot) => s + Number(slot.qtd_planejada || 0), 0), 16000);
  const metaSemana = metaDia * 5;
  const produzidoDia = Number(historicoDia.kpis?.total_produzido || 0);
  const produzidoSemana = Number(historicoSemana.kpis?.total_produzido || 0);
  const registrosDia = Number(historicoDia.kpis?.registros || 0);
  const paradasDia = (historicoDia.rows || []).filter(row => row.tipo === "pausa" || row.tipo === "perda").length;
  const mediaRegistro = registrosDia > 0 ? Math.round(produzidoDia / registrosDia) : 0;
  const weekStart = startOfWeek(day);
  const weekEnd = addDays(weekStart, 6);
  const hasActiveSlot = (slots || []).some(slot => slot.status === "em_execucao");
  const producedByLine = useMemo(() => {
    const byName = {};
    for (const row of historicoDia.rows || []) {
      if (row.tipo !== "apontamento") continue;
      const key = row.linha || "Linha";
      byName[key] = (byName[key] || 0) + Number(row.qtd || 0);
    }
    for (const linha of linhas || []) {
      const slot = slotByLinha[linha.id];
      if (slot?.linha_nome && byName[slot.linha_nome] != null) byName[linha.id] = byName[slot.linha_nome];
      if (byName[linha.nome] != null) byName[linha.id] = byName[linha.nome];
    }
    return byName;
  }, [historicoDia.rows, linhas, slotByLinha]);
  const ordersProgress = useMemo(() => {
    const map = {};
    for (const slot of slots || []) {
      const key = slot.pedido_numero || slot.op_numero || slot.id;
      map[key] = map[key] || { numero: slot.pedido_numero || slot.op_numero, produto: slot.produto_nome, produced: 0, target: 0 };
      map[key].target += Number(slot.qtd_planejada || 0);
      if (!map[key].produto) map[key].produto = slot.produto_nome;
    }
    for (const row of historicoDia.rows || []) {
      if (row.tipo !== "apontamento") continue;
      const key = row.pedido_numero || row.op_numero || row.id;
      map[key] = map[key] || { numero: row.pedido_numero || row.op_numero, produto: row.produto, produced: 0, target: 0 };
      map[key].produced += Number(row.qtd || 0);
      if (!map[key].produto) map[key].produto = row.produto;
    }
    return Object.values(map)
      .map(order => ({ ...order, target: order.target || Math.ceil((order.produced || 0) / 0.92) || 0 }))
      .sort((a, b) => (b.produced || 0) - (a.produced || 0));
  }, [historicoDia.rows, slots]);

  return (
    <div className="pcp-theme min-h-full bg-black text-white">
        <main className="mx-auto min-h-screen w-full max-w-[1440px] px-4 py-6 md:px-8 lg:px-9">
          <header className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
            <div>
              <p className="text-xs font-semibold text-zinc-500">Sistema PCP - Producao do dia</p>
              <h1 className="mt-2 text-3xl font-black tracking-tight md:text-4xl">{formatLongDate(day)}</h1>
              <div className="mt-2 flex items-center gap-2 text-xs font-bold text-[#04c821]">
                <span className="h-2 w-2 rounded-full bg-[#04c821]" /> Ao vivo
              </div>
            </div>
            <div className="flex items-center gap-2 self-end">
              <Button variant="ghost" size="icon" className="rounded-xl bg-[#171719] text-zinc-400 hover:bg-[#232326] hover:text-white" onClick={() => setDay(addDays(day, -1))}>
                <ChevronLeft className="h-4 w-4" />
              </Button>
              <div className="flex items-center gap-3 rounded-xl bg-[#171719] px-4 py-2 text-sm font-bold text-white">
                {formatBR(day)} <Calendar className="h-4 w-4 text-zinc-400" />
              </div>
              <Button variant="ghost" size="icon" className="rounded-xl bg-[#171719] text-zinc-400 hover:bg-[#232326] hover:text-white" onClick={() => setDay(addDays(day, 1))}>
                <ChevronRight className="h-4 w-4" />
              </Button>
              <Button className="rounded-xl bg-[#6485f2] px-4 font-bold hover:bg-[#7593ff]" onClick={() => setDay(toYMD(new Date()))}>Hoje</Button>
            </div>
          </header>

          {loading ? (
            <div className="mt-10 rounded-3xl bg-[#1b1b1e] p-12 text-center text-zinc-400">Carregando dashboard...</div>
          ) : (
            <div className="mt-7 space-y-5">
              <section className="rounded-3xl bg-[#1f1f22] p-5 md:p-6">
                <div className="mb-5 flex items-center justify-between gap-3">
                  <h2 className="flex items-center gap-2 text-base font-black">
                    <AlertTriangle className="h-4 w-4 text-red-500" /> Status das Linhas - OP em Andamento
                  </h2>
                  <Badge className="rounded-full bg-red-400/20 text-red-300">Tempo Real</Badge>
                </div>
                <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
                  {(activeLinhas.length ? activeLinhas : [{ nome: "Linha 1" }, { nome: "Linha 2" }, { nome: "Linha 3" }]).map((linha, idx) => (
                    <LineCard key={linha.id || idx} linha={linha} slot={slotByLinha[linha.id]} />
                  ))}
                </div>
              </section>

              <section className="rounded-3xl bg-[#1f1f22] p-5 md:p-6">
                <h2 className="mb-5 text-base font-black">Acompanhamento e Empilhamento de Metas</h2>
                <div className="space-y-4">
                  <GoalBar title={`Meta de hoje (${formatBR(day)})`} subtitle="Meta Diaria de Producao" produced={produzidoDia} target={metaDia} />
                  <GoalBar title={`Meta da semana (${formatBR(weekStart)} a ${formatBR(weekEnd)})`} subtitle="Acumulado da Semana Util" produced={produzidoSemana} target={metaSemana} />
                </div>
              </section>

              <section className="grid grid-cols-1 gap-4 lg:grid-cols-4">
                <MetricCard value={fmt(produzidoDia)} label="Total do Dia" accent="bg-blue-500" />
                <MetricCard value={fmt(registrosDia)} label="Registros" accent="bg-green-500" />
                <MetricCard value={fmt(mediaRegistro)} label="Media/Registro" accent="bg-yellow-500" />
                <MetricCard value={fmt(paradasDia)} label="Paradas" accent="bg-red-500" />
              </section>

              <section className="grid grid-cols-1 gap-4 lg:grid-cols-2">
                <LaunchesCard rows={historicoDia.rows || []} />
                <TurnosCard hasActive={hasActiveSlot} />
              </section>

              <section className="grid grid-cols-1 gap-4 lg:grid-cols-2">
                <section className="rounded-3xl bg-[#1f1f22] p-5 md:p-6">
                  <h2 className="mb-5 text-base font-black">Linhas de Envase (Envase)</h2>
                  <div className="flex min-h-[240px] items-center justify-center">
                    <div
                      className="relative h-52 w-52 rounded-full"
                      style={{ background: `conic-gradient(#12c291 0 ${Math.min((produzidoDia / Math.max(metaDia, 1)) * 360, 360)}deg, #3b82f6 0 360deg)` }}
                    >
                      <div className="absolute inset-12 rounded-full bg-[#1f1f22]" />
                    </div>
                  </div>
                </section>
                <section className="rounded-3xl bg-[#1f1f22] p-5 md:p-6">
                  <h2 className="mb-5 text-base font-black">Rotulagem & Postos de Trabalho</h2>
                  <div className="flex min-h-[240px] items-center justify-center text-sm text-zinc-500">
                    Nenhuma producao registrada hoje.
                  </div>
                </section>
              </section>

              <ProgressPanel linhas={activeLinhas} slotByLinha={slotByLinha} producedByLine={producedByLine} metaDia={metaDia} produzidoDia={produzidoDia} />

              <section className="rounded-3xl bg-[#1f1f22] p-5 md:p-6">
                <div className="mb-4 flex items-center justify-between">
                  <h2 className="text-base font-black">Programado vs Realizado</h2>
                  <button type="button" onClick={() => navigate("/pcp/planejamento")} className="min-h-8 rounded-md px-3 text-[11px] font-bold text-[#6485f2] hover:bg-[#6485f2]/10">Programar /</button>
                </div>
                <GoalBar title="" subtitle="-" produced={produzidoDia} target={(slots || []).reduce((s, slot) => s + Number(slot.qtd_planejada || 0), 0)} tone="orange" />
              </section>

              <OrdersProgress orders={ordersProgress} />
            </div>
          )}
        </main>
    </div>
  );
}
