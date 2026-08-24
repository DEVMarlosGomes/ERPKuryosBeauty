import { useCallback, useEffect, useMemo, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import api from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import {
  AlertTriangle, Calendar, CheckCircle2, Pause, Play, RotateCcw, Search, TimerReset, Wrench,
} from "lucide-react";
import { toast } from "sonner";

function fmt(n) { return Number(n || 0).toLocaleString("pt-BR"); }
function pct(done, planned) { return planned > 0 ? Math.min(Math.round((done / planned) * 100), 100) : 0; }
function nowHM() { return new Date().toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" }); }
function todayLabel() {
  return new Date().toLocaleDateString("pt-BR", { weekday: "long", day: "2-digit", month: "long", year: "numeric" });
}

const STATUS = {
  aberta: { label: "Aberta", cls: "bg-blue-100 text-blue-700", live: "Aguardando" },
  em_processo: { label: "Em producao", cls: "bg-green-100 text-green-700", live: "Operando" },
  pausada: { label: "Pausada", cls: "bg-red-100 text-red-700", live: "Parada" },
  concluida: { label: "Concluida", cls: "bg-zinc-100 text-zinc-700", live: "Encerrada" },
  cancelada: { label: "Cancelada", cls: "bg-red-100 text-red-700", live: "Cancelada" },
};

const PAUSE_TYPES = [
  ["manutencao", "Manutencao"],
  ["falta_material", "Falta de material"],
  ["almoco", "Almoco/Refeicao"],
  ["outro", "Outro"],
];

const LOSS_TYPES = [
  ["processo", "Processo"],
  ["material", "Material"],
  ["embalagem", "Embalagem"],
  ["outro", "Outro"],
];

const SETOR_PROFILES = [
  { key: "manipulacao", label: "Manipulacao", lineTypes: ["manipulacao"] },
  { key: "envase", label: "Linha de Envase", lineTypes: ["envase", "geral"] },
  { key: "rotulagem", label: "Rotulagem", lineTypes: ["rotulagem", "embalagem"] },
  { key: "logistica", label: "Logistica", lineTypes: ["logistica", "embalagem"] },
  { key: "laboratorio", label: "Laboratorio", lineTypes: ["laboratorio", "controle_qualidade"] },
];

function opItem(op) { return op?.items?.[0] || {}; }
function planned(op) { return (op?.items || []).reduce((s, item) => s + Number(item.qtd_planejada || 0), 0); }
function produced(op) { return (op?.items || []).reduce((s, item) => s + Number(item.qtd_produzida || 0), 0); }
function losses(op) { return (op?.perdas || []).reduce((s, item) => s + Number(item.quantidade || 0), 0); }
function lineName(op) { return op?.linha_nome || op?.pcp_numero || op?.linha || "Sem linha"; }

function Shell({ children }) {
  return (
    <div className="pcp-theme min-h-full bg-black text-white">
      <main className="mx-auto min-h-screen w-full max-w-[1440px] px-4 py-6 md:px-8 lg:px-9">{children}</main>
    </div>
  );
}

function DarkCard({ children, className = "" }) {
  return <section className={`rounded-2xl bg-[#1f1f22] p-5 shadow-[0_18px_45px_rgba(0,0,0,.28)] ${className}`}>{children}</section>;
}

function ActionButton({ children, icon: Icon, className = "", ...props }) {
  return (
    <Button {...props} className={`min-h-11 w-full gap-2 rounded-xl px-4 text-sm font-black ${className}`}>
      {Icon && <Icon className="h-4 w-4" />}
      {children}
    </Button>
  );
}

export default function PCPProductionPage() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const params = useParams();
  const setorAtual = SETOR_PROFILES.some((s) => s.key === params.setor) ? params.setor : "envase";
  const setorCfg = SETOR_PROFILES.find((s) => s.key === setorAtual) || SETOR_PROFILES[1];
  const [ops, setOps] = useState([]);
  const [linhas, setLinhas] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selectedId, setSelectedId] = useState("");
  const [query, setQuery] = useState("");
  const [saving, setSaving] = useState(false);
  const [apontOpen, setApontOpen] = useState(false);
  const [pauseOpen, setPauseOpen] = useState(false);
  const [lossOpen, setLossOpen] = useState(false);
  const [retroOpen, setRetroOpen] = useState(false);
  const [apontForm, setApontForm] = useState({ item_idx: "0", qtd_produzida: "", turno: "integral", observacoes: "" });
  const [pauseForm, setPauseForm] = useState({ tipo: "outro", motivo: "" });
  const [lossForm, setLossForm] = useState({ item_idx: "0", tipo: "processo", quantidade: "", unidade: "un", motivo: "" });
  const [retroForm, setRetroForm] = useState({ data: new Date().toISOString().slice(0, 10), hora: nowHM(), qtd: "", observacoes: "" });
  const opIdFromUrl = useMemo(() => new URLSearchParams(location.search).get("op") || "", [location.search]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [opsRes, linhasRes] = await Promise.all([
        api.get("/ops").catch(() => ({ data: [] })),
        api.get("/pcp/linhas").catch(() => ({ data: [] })),
      ]);
      const list = Array.isArray(opsRes.data) ? opsRes.data : [];
      setOps(list);
      setLinhas(Array.isArray(linhasRes.data) ? linhasRes.data : []);
      setSelectedId((current) => {
        if (opIdFromUrl && list.some((op) => op.id === opIdFromUrl)) return opIdFromUrl;
        return current || list.find((op) => ["em_processo", "pausada", "aberta"].includes(op.status))?.id || "";
      });
    } catch {
      toast.error("Erro ao carregar producao");
    } finally {
      setLoading(false);
    }
  }, [opIdFromUrl]);

  useEffect(() => { load(); }, [load]);

  const lineTypeByName = useMemo(() => Object.fromEntries((linhas || []).map((linha) => [linha.nome, linha.tipo || "geral"])), [linhas]);
  const activeOps = useMemo(() => ops.filter((op) => {
    if (!["aberta", "em_processo", "pausada"].includes(op.status)) return false;
    const explicit = op.setor_pcp || op.pcp_setor || op.setor;
    if (explicit) return explicit === setorAtual;
    const type = op.linha_tipo || lineTypeByName[op.linha_nome] || lineTypeByName[op.linha] || "geral";
    return setorCfg.lineTypes.includes(type) || (setorAtual === "envase" && !explicit);
  }), [ops, setorAtual, setorCfg.lineTypes, lineTypeByName]);
  const filteredOps = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return activeOps;
    return activeOps.filter((op) => `${op.numero_op} ${op.numero_pedido} ${op.cliente_nome} ${op.project_name} ${(op.items || []).map((item) => item.item).join(" ")}`.toLowerCase().includes(q));
  }, [activeOps, query]);
  const selected = ops.find((op) => op.id === selectedId) || filteredOps[0] || activeOps[0] || null;

  const byLine = useMemo(() => {
    const base = {};
    (linhas.length ? linhas.map((l) => l.nome) : ["Linha 1", "Linha 2", "Linha 3"]).forEach((name) => { base[name] = null; });
    activeOps.forEach((op) => {
      const name = lineName(op);
      if (!base[name] || op.status === "em_processo" || op.status === "pausada") base[name] = op;
    });
    return base;
  }, [activeOps, linhas]);

  const refreshOp = (updated) => {
    setOps((prev) => prev.map((op) => op.id === updated.id ? updated : op));
    setSelectedId(updated.id);
  };

  const apiError = (err, fallback = "Operacao nao concluida") => {
    const detail = err.response?.data?.detail;
    if (typeof detail === "string") return detail;
    if (detail?.message) return detail.message;
    return fallback;
  };

  const setStatus = async (op, status) => {
    setSaving(true);
    try {
      const { data } = await api.put(`/ops/${op.id}`, { status });
      refreshOp(data);
      toast.success(status === "em_processo" ? "OP iniciada" : "Status atualizado");
    } catch (err) {
      toast.error(apiError(err));
    } finally {
      setSaving(false);
    }
  };

  const apontar = async ({ retro = false } = {}) => {
    const qtd = Number(retro ? retroForm.qtd : apontForm.qtd_produzida);
    if (!selected || qtd <= 0) return toast.error("Informe uma quantidade maior que zero");
    setSaving(true);
    try {
      if (selected.status === "aberta") {
        await api.put(`/ops/${selected.id}`, { status: "em_processo" });
      }
      const payload = {
        item_idx: Number(apontForm.item_idx || 0),
        qtd_produzida: qtd,
        turno: apontForm.turno,
        setor: setorAtual,
        observacoes: retro
          ? [`Retroativo ${retroForm.data} ${retroForm.hora}`, retroForm.observacoes].filter(Boolean).join(" - ")
          : apontForm.observacoes,
      };
      if (retro) payload.horario = `${retroForm.data}T${retroForm.hora || "00:00"}:00`;
      const { data } = await api.post(`/ops/${selected.id}/apontar`, payload);
      refreshOp(data);
      setApontOpen(false);
      setRetroOpen(false);
      setApontForm({ item_idx: "0", qtd_produzida: "", turno: "integral", observacoes: "" });
      setRetroForm({ data: new Date().toISOString().slice(0, 10), hora: nowHM(), qtd: "", observacoes: "" });
      toast.success(retro ? "Apontamento retroativo registrado" : "Apontamento registrado");
    } catch (err) {
      toast.error(apiError(err, "Erro ao apontar"));
    } finally {
      setSaving(false);
    }
  };

  const pause = async () => {
    if (!selected || !pauseForm.motivo.trim()) return toast.error("Informe o motivo da parada");
    setSaving(true);
    try {
      const { data } = await api.post(`/ops/${selected.id}/pausar`, pauseForm);
      refreshOp(data);
      setPauseOpen(false);
      setPauseForm({ tipo: "outro", motivo: "" });
      toast.success("Linha/OP pausada");
    } catch (err) {
      toast.error(apiError(err, "Erro ao pausar"));
    } finally {
      setSaving(false);
    }
  };

  const resume = async () => {
    if (!selected) return;
    setSaving(true);
    try {
      const { data } = await api.post(`/ops/${selected.id}/retomar`);
      refreshOp(data);
      toast.success("Producao retomada");
    } catch (err) {
      toast.error(apiError(err, "Erro ao retomar"));
    } finally {
      setSaving(false);
    }
  };

  const loss = async () => {
    if (!selected || Number(lossForm.quantidade) <= 0) return toast.error("Informe a quantidade de perda");
    setSaving(true);
    try {
      const { data } = await api.post(`/ops/${selected.id}/perda`, {
        item_idx: Number(lossForm.item_idx || 0),
        tipo: lossForm.tipo,
        quantidade: Number(lossForm.quantidade),
        unidade: lossForm.unidade,
        motivo: lossForm.motivo,
      });
      refreshOp(data);
      setLossOpen(false);
      setLossForm({ item_idx: "0", tipo: "processo", quantidade: "", unidade: "un", motivo: "" });
      toast.success("Perda registrada");
    } catch (err) {
      toast.error(apiError(err, "Erro ao registrar perda"));
    } finally {
      setSaving(false);
    }
  };

  const finish = async () => {
    if (!selected) return;
    const progress = pct(produced(selected), planned(selected));
    if (progress < 100 && !window.confirm(`A OP esta com ${progress}% produzido. Finalizar mesmo assim?`)) return;
    await setStatus(selected, "concluida");
  };

  if (loading) {
    return (
      <Shell>
        <DarkCard className="p-12 text-center text-zinc-400">Carregando producao...</DarkCard>
      </Shell>
    );
  }

  const selectedItem = opItem(selected);
  const selectedPlanned = planned(selected);
  const selectedProduced = produced(selected);
  const selectedPct = pct(selectedProduced, selectedPlanned);
  const selectedStatus = STATUS[selected?.status] || STATUS.aberta;
  const latestLogs = (selected?.apontamentos || []).slice().reverse().slice(0, 6);

  return (
    <Shell>
      <div className="mb-4 flex w-full gap-1 overflow-x-auto rounded-2xl bg-[#1f1f22] p-1">
        {SETOR_PROFILES.map((setor) => (
          <button
            key={setor.key}
            type="button"
            onClick={() => navigate(`/pcp/apontamento/${setor.key}`)}
            className={`whitespace-nowrap rounded-xl px-4 py-2 text-sm font-black transition ${
              setorAtual === setor.key ? "bg-[#6485f2] text-white" : "text-zinc-500 hover:bg-white/5 hover:text-white"
            }`}
          >
            {setor.label}
          </button>
        ))}
      </div>
      <div className="mb-6 flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <p className="text-sm font-bold text-zinc-500">Sistema PCP - Registro de Producao</p>
          <h1 className="mt-1 text-3xl font-black tracking-tight text-white">{todayLabel()}</h1>
          <p className="mt-1 text-sm font-bold text-[#6485f2]">{setorCfg.label}</p>
          <div className="mt-2 flex items-center gap-2 text-sm font-bold text-green-500">
            <span className="h-2 w-2 rounded-full bg-green-500 shadow-[0_0_18px_rgba(34,197,94,.8)]" />
            Ao vivo
          </div>
        </div>
        <div className="rounded-2xl bg-[#1f1f22] px-5 py-3 text-right">
          <p className="text-3xl font-black text-white">{nowHM()}</p>
          <p className="text-xs font-bold uppercase tracking-wide text-zinc-500">Operador: {user?.name || "Usuario"}</p>
        </div>
      </div>

      <DarkCard className="mb-5">
        <div className="mb-4 flex items-center justify-between gap-3">
          <h2 className="text-lg font-black">Status das Linhas - OP em Andamento</h2>
          <Badge className="bg-red-100 text-red-700">Tempo Real</Badge>
        </div>
        <div className="grid grid-cols-1 gap-3 lg:grid-cols-3">
          {Object.entries(byLine).map(([line, op]) => {
            const status = STATUS[op?.status] || STATUS.aberta;
            const p = pct(produced(op), planned(op));
            return (
              <button
                key={line}
                type="button"
                onClick={() => op && setSelectedId(op.id)}
                className={`rounded-2xl border p-4 text-left transition ${
                  selected?.id === op?.id ? "border-[#6485f2] bg-[#25283a]" : op?.status === "pausada" ? "border-red-500/50 bg-red-950/20" : "border-white/10 bg-black/40 hover:border-white/25"
                }`}
              >
                <div className="mb-2 flex items-center justify-between gap-2">
                  <p className="font-black text-white">{line}</p>
                  <span className={`rounded-full px-2 py-1 text-[10px] font-black ${op?.status === "pausada" ? "bg-red-100 text-red-700" : "bg-green-950 text-green-400"}`}>
                    {op ? status.live : "Sem OP"}
                  </span>
                </div>
                {op ? (
                  <>
                    <p className="truncate text-sm font-black text-white">OP {op.numero_op} - {opItem(op).item || op.project_name || "Produto"}</p>
                    <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-zinc-300">
                      <div className="h-full bg-[#00bf20]" style={{ width: `${p}%` }} />
                    </div>
                    <div className="mt-1 flex justify-between text-xs text-zinc-400">
                      <span>{fmt(produced(op))} / {fmt(planned(op))} un.</span>
                      <span>{p}%</span>
                    </div>
                  </>
                ) : (
                  <p className="pt-3 text-sm italic text-zinc-500">Sem OP alocada</p>
                )}
              </button>
            );
          })}
        </div>
      </DarkCard>

      <div className="grid grid-cols-1 gap-5 xl:grid-cols-[360px_1fr]">
        <DarkCard className="h-fit">
          <h2 className="mb-4 text-lg font-black">Fila de OPs Ativas</h2>
          <div className="relative mb-3">
            <Search className="absolute left-3 top-3 h-4 w-4 text-zinc-500" />
            <Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Buscar OP, produto, cliente..." className="border-white/10 bg-black pl-9 text-white" />
          </div>
          <div className="max-h-[620px] space-y-2 overflow-auto pr-1">
            {filteredOps.map((op) => {
              const p = pct(produced(op), planned(op));
              const status = STATUS[op.status] || STATUS.aberta;
              return (
                <button
                  key={op.id}
                  type="button"
                  onClick={() => setSelectedId(op.id)}
                  className={`w-full rounded-xl border p-3 text-left transition ${selected?.id === op.id ? "border-[#6485f2] bg-[#25283a]" : "border-white/10 bg-black/40 hover:border-white/25"}`}
                >
                  <div className="mb-1 flex items-center justify-between gap-2">
                    <span className="font-mono text-sm font-black text-white">{op.numero_op}</span>
                    <Badge className={status.cls}>{status.label}</Badge>
                  </div>
                  <p className="truncate text-sm font-black text-white">{opItem(op).item || op.project_name || "Produto"}</p>
                  <p className="truncate text-xs text-zinc-500">{op.cliente_nome || "Cliente"} - {lineName(op)}</p>
                  <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-zinc-300">
                    <div className="h-full bg-[#6485f2]" style={{ width: `${p}%` }} />
                  </div>
                </button>
              );
            })}
            {filteredOps.length === 0 && <p className="py-8 text-center text-sm text-zinc-500">Nenhuma OP ativa encontrada.</p>}
          </div>
        </DarkCard>

        <div className="space-y-5">
          <DarkCard>
            {selected ? (
              <>
                <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
                  <div className="min-w-0">
                    <div className="mb-2 flex flex-wrap items-center gap-2">
                      <Badge className={selectedStatus.cls}>{selectedStatus.label}</Badge>
                      <Badge className="bg-violet-100 text-violet-700">Pedido #{selected.numero_pedido || "-"}</Badge>
                      <Badge className="bg-zinc-100 text-zinc-700">{lineName(selected)}</Badge>
                    </div>
                    <h2 className="truncate text-2xl font-black text-white">OP {selected.numero_op}</h2>
                    <p className="mt-1 truncate text-base font-bold text-zinc-300">{selectedItem.item || selected.project_name || "Produto sem descricao"}</p>
                    <p className="text-sm text-zinc-500">{selected.cliente_nome || "Cliente"} - SKU {selectedItem.codigo_kuryos || "-"}</p>
                  </div>
                  <div className="text-left lg:text-right">
                    <p className="text-4xl font-black text-[#6485f2]">{selectedPct}%</p>
                    <p className="text-xs font-bold uppercase tracking-wide text-zinc-500">concluido</p>
                  </div>
                </div>

                <div className="mt-5 h-3 overflow-hidden rounded-full bg-zinc-300">
                  <div className={`h-full ${selected.status === "pausada" ? "bg-red-500" : "bg-[#00bf20]"}`} style={{ width: `${selectedPct}%` }} />
                </div>
                <div className="mt-2 flex flex-wrap justify-between gap-3 text-sm text-zinc-400">
                  <span>Produzido: <b className="text-white">{fmt(selectedProduced)}</b></span>
                  <span>Meta: <b className="text-white">{fmt(selectedPlanned)}</b></span>
                  <span>Saldo: <b className="text-white">{fmt(Math.max(selectedPlanned - selectedProduced, 0))}</b></span>
                  <span>Perdas: <b className="text-red-400">{fmt(losses(selected))}</b></span>
                </div>

                <div className="mt-6 grid grid-cols-[repeat(auto-fit,minmax(170px,1fr))] gap-3">
                  {selected.status === "aberta" && (
                    <ActionButton icon={Play} disabled={saving} className="bg-[#00bf20] hover:bg-[#00a91c]" onClick={() => setStatus(selected, "em_processo")}>Abrir OP</ActionButton>
                  )}
                  {selected.status === "em_processo" && (
                    <>
                      <ActionButton icon={TimerReset} disabled={saving} className="bg-[#6485f2] hover:bg-[#7593ff]" onClick={() => setApontOpen(true)}>Apontamento Total</ActionButton>
                      <ActionButton icon={Pause} disabled={saving} className="bg-amber-600 hover:bg-amber-700" onClick={() => setPauseOpen(true)}>Parar Linha</ActionButton>
                      <ActionButton icon={AlertTriangle} disabled={saving} className="bg-red-600 hover:bg-red-700" onClick={() => setLossOpen(true)}>Adicionar Perda</ActionButton>
                      <ActionButton icon={CheckCircle2} disabled={saving} className="bg-[#00bf20] hover:bg-[#00a91c]" onClick={finish}>Finalizar OP</ActionButton>
                    </>
                  )}
                  {selected.status === "pausada" && (
                    <ActionButton icon={RotateCcw} disabled={saving} className="bg-[#00bf20] hover:bg-[#00a91c]" onClick={resume}>Retomar</ActionButton>
                  )}
                  {["aberta", "em_processo"].includes(selected.status) && (
                    <ActionButton icon={Calendar} disabled={saving} className="bg-zinc-700 text-white hover:bg-zinc-600" onClick={() => setRetroOpen(true)}>Turno Retroativo</ActionButton>
                  )}
                  <ActionButton icon={Wrench} variant="outline" className="border-white/20 bg-transparent text-white hover:bg-white/10" onClick={() => navigate(`/ops/${selected.id}`)}>Detalhe da OP</ActionButton>
                </div>
              </>
            ) : (
              <div className="py-16 text-center text-zinc-500">Selecione uma OP ativa.</div>
            )}
          </DarkCard>

          <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
            <DarkCard>
              <h3 className="mb-4 text-base font-black">Ultimos Registros de Hoje</h3>
              <div className="space-y-2">
                {latestLogs.map((log) => (
                  <div key={log.id} className="flex items-center justify-between gap-3 rounded-lg border border-white/10 bg-black/40 px-3 py-2 text-sm">
                    <div className="min-w-0">
                      <p className="truncate font-bold text-white">{log.item_nome || "Apontamento"}</p>
                      <p className="text-xs text-zinc-500">{log.horario ? new Date(log.horario).toLocaleString("pt-BR") : "-"} - {log.por || "Operador"}</p>
                    </div>
                    <span className="font-mono font-black text-green-400">+{fmt(log.qtd_produzida)}</span>
                  </div>
                ))}
                {latestLogs.length === 0 && <p className="py-8 text-center text-sm text-zinc-500">Nenhum apontamento nesta OP.</p>}
              </div>
            </DarkCard>
            <DarkCard>
              <h3 className="mb-4 text-base font-black">Paradas e Perdas</h3>
              <div className="space-y-2">
                {(selected?.pausas || []).slice().reverse().slice(0, 4).map((pause) => (
                  <div key={pause.id} className="rounded-lg border border-amber-500/20 bg-amber-950/10 px-3 py-2 text-sm">
                    <div className="flex items-center justify-between gap-2">
                      <p className="font-bold text-amber-300">{pause.motivo || "Parada"}</p>
                      <Badge className={pause.horario_fim ? "bg-zinc-100 text-zinc-700" : "bg-red-100 text-red-700"}>{pause.horario_fim ? "Encerrada" : "Aberta"}</Badge>
                    </div>
                    <p className="mt-1 text-xs text-zinc-500">{pause.tipo} - {pause.duracao_min != null ? `${pause.duracao_min} min` : "em andamento"}</p>
                  </div>
                ))}
                {(selected?.perdas || []).slice().reverse().slice(0, 4).map((lossItem) => (
                  <div key={lossItem.id} className="flex items-center justify-between rounded-lg border border-red-500/20 bg-red-950/10 px-3 py-2 text-sm">
                    <div>
                      <p className="font-bold text-red-300">{lossItem.motivo || lossItem.tipo}</p>
                      <p className="text-xs text-zinc-500">{lossItem.item_nome || "Item"} - {lossItem.por}</p>
                    </div>
                    <span className="font-mono font-black text-red-400">-{fmt(lossItem.quantidade)} {lossItem.unidade}</span>
                  </div>
                ))}
                {!(selected?.pausas || []).length && !(selected?.perdas || []).length && <p className="py-8 text-center text-sm text-zinc-500">Sem paradas ou perdas registradas.</p>}
              </div>
            </DarkCard>
          </div>
        </div>
      </div>

      <Dialog open={apontOpen} onOpenChange={setApontOpen}>
        <DialogContent className="pcp-theme max-w-md border-white/10 bg-[#1f1f22] text-white">
          <DialogHeader><DialogTitle>Apontamento por Total da OP</DialogTitle></DialogHeader>
          <ProductionForm selected={selected} form={apontForm} setForm={setApontForm} />
          <DialogFooter>
            <Button variant="outline" className="border-white/20 bg-transparent text-white" onClick={() => setApontOpen(false)}>Cancelar</Button>
            <Button className="bg-[#6485f2]" disabled={saving} onClick={() => apontar()}>Salvar Registro</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={pauseOpen} onOpenChange={setPauseOpen}>
        <DialogContent className="pcp-theme max-w-md border-white/10 bg-[#1f1f22] text-white">
          <DialogHeader><DialogTitle>Parar Linha</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <div>
              <Label>Tipo</Label>
              <Select value={pauseForm.tipo} onValueChange={(v) => setPauseForm((f) => ({ ...f, tipo: v }))}>
                <SelectTrigger className="mt-1 border-white/10 bg-black text-white"><SelectValue /></SelectTrigger>
                <SelectContent>{PAUSE_TYPES.map(([v, l]) => <SelectItem key={v} value={v}>{l}</SelectItem>)}</SelectContent>
              </Select>
            </div>
            <div>
              <Label>Motivo *</Label>
              <Input value={pauseForm.motivo} onChange={(e) => setPauseForm((f) => ({ ...f, motivo: e.target.value }))} className="mt-1 border-white/10 bg-black text-white" autoFocus />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" className="border-white/20 bg-transparent text-white" onClick={() => setPauseOpen(false)}>Cancelar</Button>
            <Button className="bg-red-600 hover:bg-red-700" disabled={saving} onClick={pause}>Confirmar Parada</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={lossOpen} onOpenChange={setLossOpen}>
        <DialogContent className="pcp-theme max-w-md border-white/10 bg-[#1f1f22] text-white">
          <DialogHeader><DialogTitle>Adicionar Perda</DialogTitle></DialogHeader>
          <div className="space-y-3">
            {(selected?.items || []).length > 1 && (
              <div>
                <Label>Item</Label>
                <Select value={lossForm.item_idx} onValueChange={(v) => setLossForm((f) => ({ ...f, item_idx: v }))}>
                  <SelectTrigger className="mt-1 border-white/10 bg-black text-white"><SelectValue /></SelectTrigger>
                  <SelectContent>{(selected?.items || []).map((item, idx) => <SelectItem key={idx} value={String(idx)}>{item.item || `Item ${idx + 1}`}</SelectItem>)}</SelectContent>
                </Select>
              </div>
            )}
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label>Tipo</Label>
                <Select value={lossForm.tipo} onValueChange={(v) => setLossForm((f) => ({ ...f, tipo: v }))}>
                  <SelectTrigger className="mt-1 border-white/10 bg-black text-white"><SelectValue /></SelectTrigger>
                  <SelectContent>{LOSS_TYPES.map(([v, l]) => <SelectItem key={v} value={v}>{l}</SelectItem>)}</SelectContent>
                </Select>
              </div>
              <div>
                <Label>Unidade</Label>
                <Select value={lossForm.unidade} onValueChange={(v) => setLossForm((f) => ({ ...f, unidade: v }))}>
                  <SelectTrigger className="mt-1 border-white/10 bg-black text-white"><SelectValue /></SelectTrigger>
                  <SelectContent>{["un", "kg", "L", "g", "mL"].map((u) => <SelectItem key={u} value={u}>{u}</SelectItem>)}</SelectContent>
                </Select>
              </div>
            </div>
            <div>
              <Label>Quantidade *</Label>
              <Input type="number" value={lossForm.quantidade} onChange={(e) => setLossForm((f) => ({ ...f, quantidade: e.target.value }))} className="mt-1 border-white/10 bg-black text-white" autoFocus />
            </div>
            <div>
              <Label>Motivo</Label>
              <Textarea value={lossForm.motivo} onChange={(e) => setLossForm((f) => ({ ...f, motivo: e.target.value }))} className="mt-1 border-white/10 bg-black text-white" rows={3} />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" className="border-white/20 bg-transparent text-white" onClick={() => setLossOpen(false)}>Cancelar</Button>
            <Button className="bg-red-600 hover:bg-red-700" disabled={saving} onClick={loss}>Adicionar perda</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={retroOpen} onOpenChange={setRetroOpen}>
        <DialogContent className="pcp-theme max-w-md border-white/10 bg-[#1f1f22] text-white">
          <DialogHeader><DialogTitle>Registrar turno retroativo</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label>Data</Label>
                <Input type="date" value={retroForm.data} onChange={(e) => setRetroForm((f) => ({ ...f, data: e.target.value }))} className="mt-1 border-white/10 bg-black text-white" />
              </div>
              <div>
                <Label>Hora</Label>
                <Input type="time" value={retroForm.hora} onChange={(e) => setRetroForm((f) => ({ ...f, hora: e.target.value }))} className="mt-1 border-white/10 bg-black text-white" />
              </div>
            </div>
            <div>
              <Label>Quantidade produzida *</Label>
              <Input type="number" value={retroForm.qtd} onChange={(e) => setRetroForm((f) => ({ ...f, qtd: e.target.value }))} className="mt-1 border-white/10 bg-black text-white" autoFocus />
            </div>
            <div>
              <Label>Observacoes</Label>
              <Textarea value={retroForm.observacoes} onChange={(e) => setRetroForm((f) => ({ ...f, observacoes: e.target.value }))} className="mt-1 border-white/10 bg-black text-white" rows={3} />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" className="border-white/20 bg-transparent text-white" onClick={() => setRetroOpen(false)}>Cancelar</Button>
            <Button className="bg-[#6485f2]" disabled={saving} onClick={() => apontar({ retro: true })}>Registrar</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Shell>
  );
}

function ProductionForm({ selected, form, setForm }) {
  return (
    <div className="space-y-3">
      {(selected?.items || []).length > 1 && (
        <div>
          <Label>Item</Label>
          <Select value={form.item_idx} onValueChange={(v) => setForm((f) => ({ ...f, item_idx: v }))}>
            <SelectTrigger className="mt-1 border-white/10 bg-black text-white"><SelectValue /></SelectTrigger>
            <SelectContent>{(selected?.items || []).map((item, idx) => <SelectItem key={idx} value={String(idx)}>{item.item || `Item ${idx + 1}`}</SelectItem>)}</SelectContent>
          </Select>
        </div>
      )}
      <div>
        <Label>Quantidade produzida *</Label>
        <Input type="number" min="0" value={form.qtd_produzida} onChange={(e) => setForm((f) => ({ ...f, qtd_produzida: e.target.value }))} className="mt-1 border-white/10 bg-black text-white" autoFocus />
      </div>
      <div>
        <Label>Turno</Label>
        <Select value={form.turno} onValueChange={(v) => setForm((f) => ({ ...f, turno: v }))}>
          <SelectTrigger className="mt-1 border-white/10 bg-black text-white"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="manha">Manha</SelectItem>
            <SelectItem value="tarde">Tarde</SelectItem>
            <SelectItem value="noite">Noite</SelectItem>
            <SelectItem value="integral">Integral</SelectItem>
          </SelectContent>
        </Select>
      </div>
      <div>
        <Label>Operador</Label>
        <Input disabled value="Usuario atual" className="mt-1 border-white/10 bg-zinc-900 text-zinc-400" />
      </div>
      <div>
        <Label>Observacoes</Label>
        <Textarea value={form.observacoes} onChange={(e) => setForm((f) => ({ ...f, observacoes: e.target.value }))} className="mt-1 border-white/10 bg-black text-white" rows={3} />
      </div>
    </div>
  );
}
