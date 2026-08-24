import { useState, useEffect, useCallback, useRef } from "react";
import api from "@/lib/api";
import { formatApiError } from "@/lib/formatError";
import { getCurrentBackendUrl, toWebSocketUrl } from "@/lib/backend";
import { DragDropContext, Droppable, Draggable } from "@hello-pangea/dnd";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { GripVertical, Building2, Calendar, Plus, Sparkles, ExternalLink, UserCircle2, X, Loader2 } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { useAuth } from "@/contexts/AuthContext";
import PDSubNav from "@/components/PDSubNav";
import ViewSwitcher from "@/components/ViewSwitcher";
import FilterBar, { applyFilters } from "@/components/FilterBar";
import ListView from "@/components/ListView";

const STAGES = [
    { id: "solicitado", label: "Aberto", color: "bg-gray-400" },
    { id: "em_desenvolvimento", label: "Em Desenvolvimento", color: "bg-blue-400" },
    { id: "em_testes", label: "Em Testes", color: "bg-purple-400" },
    { id: "aguardando_aprovacao", label: "Aguardando Aprovação", color: "bg-yellow-400" },
    { id: "retrabalho_interno", label: "Retrabalho", color: "bg-red-400" },
    { id: "aprovado", label: "Aprovado", color: "bg-green-500" },
    { id: "concluido", label: "Concluído", color: "bg-emerald-600" },
];

function initials(name) {
    if (!name) return "?";
    return name.split(" ").slice(0, 2).map(n => n[0]).join("").toUpperCase();
}

export default function PDPage() {
    const { user: authUser } = useAuth();
    const canAssignExecutor = authUser && ["admin", "lider_pd", "formulador", "engenharia_produto"].includes(authUser.role);
    const [cards, setCards] = useState([]);
    const [loading, setLoading] = useState(true);
    const [search, setSearch] = useState("");
    const [view, setView] = useState(() => localStorage.getItem("pd:view") || "kanban");
    const [filters, setFilters] = useState({});
    const [selectedCard, setSelectedCard] = useState(null);
    const [showResearch, setShowResearch] = useState(false);
    const [executorDialog, setExecutorDialog] = useState(null); // { cardId, currentName }
    const [executorSearch, setExecutorSearch] = useState("");
    const [executorUsers, setExecutorUsers] = useState([]);
    const [loadingExecutors, setLoadingExecutors] = useState(false);
    const [assigningExecutor, setAssigningExecutor] = useState(false);
    const [researchForm, setResearchForm] = useState({
        project_name: "",
        objectives: "",
        description: "",
        category: "",
        references: "",
        priority: "Normal",
        deadline: "",
    });
    const [creatingResearch, setCreatingResearch] = useState(false);
    const wsRef = useRef(null);
    const navigate = useNavigate();

    useEffect(() => {
        localStorage.setItem("pd:view", view);
    }, [view]);

    const loadCards = useCallback(async () => {
        try {
            const params = search ? { search } : {};
            const { data } = await api.get("/crm/pd/cards", { params });
const validCards = Array.isArray(data) ? data.filter(c => c && c.id) : (Array.isArray(data?.items) ? data.items.filter(c => c && c.id) : []);
            setCards(validCards);
        } catch (e) {
            console.error("Failed to load P&D cards", e);
            setCards([]);
        } finally {
            setLoading(false);
        }
    }, [search]);

    useEffect(() => { loadCards(); }, [loadCards]);

    useEffect(() => {
        const wsBackendUrl = toWebSocketUrl(getCurrentBackendUrl());
        if (!wsBackendUrl) return undefined;

        let disposed = false;
        let reconnectTimer = null;

        const connectWs = () => {
            if (disposed) return;
            try {
                const ws = new WebSocket(`${wsBackendUrl}/api/ws`);

                ws.onmessage = (event) => {
                    try {
                        const msg = JSON.parse(event.data);
                        if (msg.event !== "pd_card_moved") return;

                        const incomingCard = msg.data?.card;
                        if (!incomingCard?.id) return;

                        setCards((current) => {
                            const index = current.findIndex((card) => card.id === incomingCard.id);
                            if (index === -1) {
                                return [incomingCard, ...current];
                            }
                            const next = [...current];
                            next[index] = { ...next[index], ...incomingCard };
                            return next;
                        });
                    } catch {}
                };

                ws.onclose = () => {
                    if (disposed) return;
                    reconnectTimer = window.setTimeout(connectWs, 5000);
                };

                ws.onerror = () => {
                    ws.close();
                };

                wsRef.current = ws;
            } catch {
                reconnectTimer = window.setTimeout(connectWs, 5000);
            }
        };

        connectWs();

        return () => {
            disposed = true;
            if (reconnectTimer) {
                window.clearTimeout(reconnectTimer);
            }
            if (wsRef.current) {
                wsRef.current.close();
                wsRef.current = null;
            }
        };
    }, []);

    const cardsByStage = STAGES.reduce((acc, stage) => {
        acc[stage.id] = cards.filter(c => c.status_pd === stage.id);
        return acc;
    }, {});

    const handleDragEnd = async (result) => {
        if (!result.destination) return;
        const { draggableId, source, destination } = result;
        if (source.droppableId === destination.droppableId) return;

        const newStatus = destination.droppableId;

        try {
            const { data } = await api.put(`/crm/pd/cards/${draggableId}/move`, {
                status: newStatus,
                observacao: ""
            });
            toast.success(`Card movido para ${data.to_status}`);
            if (data.synced_to_crm) {
                toast.success("Sincronizado com CRM Comercial!", { duration: 3000 });
            }
            loadCards();
        } catch (e) {
            toast.error(formatApiError(e));
        }
    };

    const createInternalResearch = async () => {
        if (!researchForm.project_name.trim()) {
            return toast.error("Nome do projeto é obrigatório");
        }
        setCreatingResearch(true);
        try {
            const payload = {
                ...researchForm,
                deadline: researchForm.deadline || null,
            };
            const { data } = await api.post("/pd/requests/internal-research", payload);
            toast.success(`Pesquisa Interna criada! (${data.id?.slice(0, 8)})`);
            setShowResearch(false);
            setResearchForm({
                project_name: "", objectives: "", description: "", category: "",
                references: "", priority: "Normal", deadline: "",
            });
            loadCards();
            // Navigate to detail page (PDDetail)
            if (data.id) {
                setTimeout(() => navigate(`/pd/${data.id}`), 600);
            }
        } catch (e) {
            toast.error(formatApiError(e));
        } finally {
            setCreatingResearch(false);
        }
    };

    const openExecutorDialog = async (e, card) => {
        e.stopPropagation();
        setExecutorDialog({ cardId: card.id, currentName: card.executor_name });
        setExecutorSearch("");
        setExecutorUsers([]);
        setLoadingExecutors(true);
        try {
            const { data } = await api.get("/users", { params: { roles: "admin,lider_pd,formulador,engenharia_produto,qa" } });
            setExecutorUsers(Array.isArray(data) ? data : []);
        } catch { setExecutorUsers([]); } finally { setLoadingExecutors(false); }
    };

    const assignExecutor = async (userId, userName) => {
        if (!executorDialog) return;
        setAssigningExecutor(true);
        try {
            await api.put(`/pd/pd-cards/${executorDialog.cardId}/executor`, { executor_id: userId, executor_name: userName });
            toast.success(`Executor atribuído: ${userName}`);
            setExecutorDialog(null);
            loadCards();
        } catch (err) { toast.error(formatApiError(err)); }
        finally { setAssigningExecutor(false); }
    };

    const openCardDetail = async (card) => {
        // If linked to pd_request, navigate to full detail page (like Abelinha print)
        if (card.pd_request_id) {
            navigate(`/pd/${card.pd_request_id}`);
            return;
        }
        // Lazy: fetch single card to trigger backend auto-creation of pd_request, then navigate
        try {
            const { data } = await api.get(`/crm/pd/cards/${card.id}`);
            if (data?.pd_request_id) {
                navigate(`/pd/${data.pd_request_id}`);
                return;
            }
        } catch (e) {
            // Fall back to side sheet on error
        }
        setSelectedCard(card);
    };

    if (loading) return (
        <div className="p-6 page-enter">
            <PDSubNav active="pd" />
            <div className="flex gap-4">
                {[1, 2, 3, 4, 5].map(i => <div key={i} className="h-96 w-64 bg-muted rounded-lg animate-pulse" />)}
            </div>
        </div>
    );

    return (
        <div className="p-6 page-enter">
            <PDSubNav active="pd" />
            <div className="flex items-center justify-between mb-4">
                <div>
                    <h1 className="text-3xl font-heading font-semibold tracking-tight">Pipeline P&D</h1>
                    <p className="text-sm text-muted-foreground mt-1">{cards.length} cards em desenvolvimento</p>
                </div>
                <div className="flex items-center gap-2">
                    <ViewSwitcher value={view} onChange={setView} testIdPrefix="pd" />
                    <Button onClick={() => setShowResearch(true)} className="gap-1.5">
                        <Sparkles className="h-4 w-4" /> Nova Pesquisa Interna
                    </Button>
                </div>
            </div>

            {(() => {
                const filterFields = [
                    {
                        key: "search",
                        type: "search",
                        placeholder: "Buscar por número, produto, cliente ou aplicação...",
                        searchKeys: [
                            (c) => c.numero_completo,
                            (c) => c.produto,
                            (c) => c.cliente,
                            (c) => c.descricao_aplicacao,
                            (c) => c.responsavel_pd,
                        ],
                    },
                    {
                        key: "status_pd",
                        type: "multi",
                        label: "Status",
                        options: STAGES.map((s) => ({ value: s.id, label: s.label })),
                        getter: (c) => c.status_pd,
                    },
                    {
                        key: "responsavel_pd",
                        type: "select",
                        label: "Responsável P&D",
                        options: Array.from(new Set(cards.map((c) => c.responsavel_pd).filter(Boolean)))
                            .map((v) => ({ value: v, label: v })),
                        getter: (c) => c.responsavel_pd,
                    },
                    {
                        key: "cliente",
                        type: "select",
                        label: "Cliente",
                        options: Array.from(new Set(cards.map((c) => c.cliente).filter(Boolean)))
                            .map((v) => ({ value: v, label: v })),
                        getter: (c) => c.cliente,
                    },
                    {
                        key: "is_internal_research",
                        type: "select",
                        label: "Origem",
                        options: [
                            { value: "true", label: "Pesquisa Interna" },
                            { value: "false", label: "Cliente" },
                        ],
                        getter: (c) => String(Boolean(c.is_internal_research)),
                    },
                ];
                const filteredCards = applyFilters(cards, filters, filterFields);
                const filteredByStage = STAGES.reduce((acc, s) => {
                    acc[s.id] = filteredCards.filter((c) => c.status_pd === s.id);
                    return acc;
                }, {});

                return (
                    <>
                        <FilterBar
                            filters={filters}
                            onChange={setFilters}
                            fields={filterFields}
                            testIdPrefix="pd-filter"
                        />

                        {view === "kanban" ? (
            <DragDropContext onDragEnd={handleDragEnd}>
                <div className="kanban-board">
                    {STAGES.map((stage) => (
                        <Droppable droppableId={stage.id} key={stage.id}>
                            {(provided, snapshot) => (
                                <div
                                    ref={provided.innerRef}
                                    {...provided.droppableProps}
                                    className={`kanban-column rounded-lg ${snapshot.isDraggingOver ? "bg-accent/50" : "bg-muted/30"}`}
                                >
                                    <div className="p-3 border-b border-border">
                                        <div className="flex items-center gap-2">
                                            <div className={`w-2 h-2 rounded-full ${stage.color}`} />
                                            <h3 className="font-heading font-medium text-sm truncate">{stage.label}</h3>
                                            <span className="text-xs text-muted-foreground mono-num ml-auto">
                                                {(filteredByStage[stage.id] || []).length}
                                            </span>
                                        </div>
                                    </div>
                                    <div className="p-2 space-y-2 min-h-[200px]">
                                        {(filteredByStage[stage.id] || []).map((card, index) => (
                                            <Draggable draggableId={card.id} index={index} key={card.id}>
                                                {(provided, snapshot) => (
                                                    <div
                                                        ref={provided.innerRef}
                                                        {...provided.draggableProps}
                                                        className={`bg-card border border-border rounded-md p-3 cursor-pointer transition-transform duration-150 ${
                                                            snapshot.isDragging ? "kanban-card-dragging" : "hover:-translate-y-0.5 hover:shadow-sm"
                                                        } ${card.is_internal_research ? "border-purple-300 bg-purple-50/30 dark:bg-purple-950/10" : ""}`}
                                                        onClick={() => openCardDetail(card)}
                                                    >
                                                        <div className="flex items-start justify-between gap-2">
                                                            <div className="flex-1 min-w-0">
                                                                <div className="flex items-center gap-2 mb-1">
                                                                    <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold mono-num ${card.is_internal_research ? "bg-purple-500/20 text-purple-700 dark:text-purple-300" : "bg-primary/10 text-primary"}`}>
                                                                        {String(card.numero_completo || '?')}
                                                                    </span>
                                                                    {card.is_internal_research && (
                                                                        <Badge variant="outline" className="text-[9px] h-4 px-1 border-purple-300 text-purple-600">
                                                                            <Sparkles className="h-2.5 w-2.5 mr-0.5" /> Pesquisa
                                                                        </Badge>
                                                                    )}
                                                                </div>
                                                                <p className="font-body font-medium text-sm truncate">
                                                                    {String(card.produto || '')}
                                                                </p>
                                                                {card.descricao_aplicacao && (
                                                                    <p className="text-xs text-muted-foreground mt-1 truncate">
                                                                        {String(card.descricao_aplicacao)}
                                                                    </p>
                                                                )}
                                                                <p className="text-xs text-muted-foreground flex items-center gap-1 mt-1">
                                                                    <Building2 className="h-3 w-3" />
                                                                    {String(card.cliente || '')}
                                                                </p>
                                                                {card.responsavel_pd && (
                                                                    <p className="text-xs text-muted-foreground mt-0.5">
                                                                        Responsável: {String(card.responsavel_pd)}
                                                                    </p>
                                                                )}
                                                                {/* PD-13: Executor avatar */}
                                                                <div className="flex items-center justify-between mt-2">
                                                                    {card.executor_name ? (
                                                                        <button
                                                                            onClick={e => canAssignExecutor ? openExecutorDialog(e, card) : e.stopPropagation()}
                                                                            className="flex items-center gap-1.5 text-[10px] text-muted-foreground hover:text-foreground transition-colors"
                                                                        >
                                                                            <div className="h-5 w-5 rounded-full bg-primary/20 text-primary flex items-center justify-center text-[9px] font-bold">
                                                                                {initials(card.executor_name)}
                                                                            </div>
                                                                            {card.executor_name.split(" ")[0]}
                                                                        </button>
                                                                    ) : canAssignExecutor ? (
                                                                        <button
                                                                            onClick={e => openExecutorDialog(e, card)}
                                                                            className="text-[10px] text-muted-foreground/60 hover:text-muted-foreground transition-colors flex items-center gap-1"
                                                                        >
                                                                            <UserCircle2 className="h-3.5 w-3.5" /> Atribuir
                                                                        </button>
                                                                    ) : <span />}
                                                                </div>
                                                            </div>
                                                            <div {...provided.dragHandleProps} className="shrink-0">
                                                                <GripVertical className="h-4 w-4 text-muted-foreground/50" />
                                                            </div>
                                                        </div>
                                                    </div>
                                                )}
                                            </Draggable>
                                        ))}
                                        {provided.placeholder}
                                    </div>
                                </div>
                            )}
                        </Droppable>
                    ))}
                </div>
            </DragDropContext>
                        ) : (
                            <ListView
                                items={filteredCards}
                                onRowClick={openCardDetail}
                                emptyMessage="Nenhum card P&D corresponde aos filtros."
                                testIdPrefix="pd-list"
                                columns={[
                                    { key: "numero_completo", label: "Número",
                                      render: (c) => (
                                          <span className={`font-mono text-xs font-semibold ${c.is_internal_research ? "text-purple-600" : "text-primary"}`}>
                                              {c.numero_completo || "?"}
                                          </span>
                                      ) },
                                    { key: "produto", label: "Produto",
                                      render: (c) => <span className="font-medium">{c.produto || "—"}</span> },
                                    { key: "descricao_aplicacao", label: "Aplicação",
                                      render: (c) => c.descricao_aplicacao || "—" },
                                    { key: "cliente", label: "Cliente",
                                      render: (c) => c.cliente || (c.is_internal_research ? "— Pesquisa Interna —" : "—") },
                                    { key: "responsavel_pd", label: "Responsável P&D",
                                      render: (c) => c.responsavel_pd || "Não atribuído" },
                                    { key: "status_pd", label: "Status",
                                      render: (c) => (
                                          <Badge variant="outline" className="text-[10px]">
                                              {STAGES.find((s) => s.id === c.status_pd)?.label || c.status_pd}
                                          </Badge>
                                      ) },
                                    { key: "prazo_prometido", label: "Prazo",
                                      render: (c) => c.prazo_prometido ? new Date(c.prazo_prometido).toLocaleDateString("pt-BR") : "—" },
                                ]}
                            />
                        )}
                    </>
                );
            })()}

            {/* PD-13: Executor assign dialog */}
            <Dialog open={!!executorDialog} onOpenChange={(open) => !open && setExecutorDialog(null)}>
                <DialogContent className="max-w-sm">
                    <DialogHeader>
                        <DialogTitle className="flex items-center gap-2">
                            <UserCircle2 className="h-4 w-4" /> Atribuir Executor
                        </DialogTitle>
                        <DialogDescription>Selecione quem vai executar este desenvolvimento.</DialogDescription>
                    </DialogHeader>
                    <div className="space-y-2">
                        <Input
                            value={executorSearch}
                            onChange={e => setExecutorSearch(e.target.value)}
                            placeholder="Filtrar por nome..."
                            className="h-8 text-sm"
                        />
                        {loadingExecutors ? (
                            <div className="flex items-center gap-2 text-xs text-muted-foreground py-2"><Loader2 className="h-3.5 w-3.5 animate-spin" /> Carregando...</div>
                        ) : (
                            <div className="border rounded-md divide-y max-h-48 overflow-y-auto">
                                {(executorUsers.filter(u => !executorSearch || u.name?.toLowerCase().includes(executorSearch.toLowerCase()))).map(u => (
                                    <button
                                        key={u.id}
                                        onClick={() => assignExecutor(u.id, u.name)}
                                        disabled={assigningExecutor}
                                        className={`w-full flex items-center gap-2 p-2 text-sm hover:bg-muted/50 transition-colors ${executorDialog?.currentName === u.name ? "bg-primary/5 font-semibold" : ""}`}
                                    >
                                        <div className="h-6 w-6 rounded-full bg-primary/20 text-primary flex items-center justify-center text-[10px] font-bold shrink-0">
                                            {initials(u.name)}
                                        </div>
                                        <span className="flex-1 text-left truncate">{u.name}</span>
                                        <span className="text-[10px] text-muted-foreground">{u.role}</span>
                                    </button>
                                ))}
                                {executorUsers.filter(u => !executorSearch || u.name?.toLowerCase().includes(executorSearch.toLowerCase())).length === 0 && (
                                    <p className="text-xs text-muted-foreground text-center py-3">Nenhum usuário encontrado</p>
                                )}
                            </div>
                        )}
                        {executorDialog?.currentName && (
                            <Button size="sm" variant="outline" className="w-full gap-1 text-xs text-muted-foreground" onClick={() => assignExecutor(null, null)}>
                                <X className="h-3 w-3" /> Remover executor
                            </Button>
                        )}
                    </div>
                </DialogContent>
            </Dialog>

            {/* Card Detail Sheet */}
            <Sheet open={!!selectedCard} onOpenChange={(open) => !open && setSelectedCard(null)}>
                <SheetContent className="w-[480px] sm:w-[520px] p-0 flex flex-col" side="right">
                    {selectedCard && (
                        <>
                            <SheetHeader className="p-6 pb-3">
                                <SheetTitle className="font-heading text-xl">
                                    {String(selectedCard?.numero_completo || 'Card P&D')}
                                </SheetTitle>
                                <div className="flex items-center gap-2 mt-1 flex-wrap">
                                    <Badge variant="outline" className="text-xs">{String(selectedCard?.cliente || '')}</Badge>
                                    <Badge className="text-xs">{String(selectedCard?.produto || '')}</Badge>
                                </div>
                            </SheetHeader>
                            <div className="flex-1 overflow-y-auto px-6 py-4">
                                <div className="space-y-4">
                                    <div>
                                        <p className="text-xs font-semibold text-muted-foreground mb-1">Status</p>
                                        <Badge>{STAGES.find(s => s.id === selectedCard.status_pd)?.label || selectedCard.status_pd}</Badge>
                                    </div>
                                    {selectedCard.descricao_aplicacao && (
                                        <div>
                                            <p className="text-xs font-semibold text-muted-foreground mb-1">Descrição da Aplicação</p>
                                            <p className="text-sm">{selectedCard.descricao_aplicacao}</p>
                                        </div>
                                    )}
                                    {selectedCard.briefing_base && (
                                        <div>
                                            <p className="text-xs font-semibold text-muted-foreground mb-1">Briefing Base</p>
                                            <p className="text-sm whitespace-pre-wrap">{selectedCard.briefing_base}</p>
                                        </div>
                                    )}
                                    {selectedCard.observacoes_especificas && (
                                        <div>
                                            <p className="text-xs font-semibold text-muted-foreground mb-1">Observações Específicas</p>
                                            <p className="text-sm">{selectedCard.observacoes_especificas}</p>
                                        </div>
                                    )}
                                    {(selectedCard.feedback_cliente || selectedCard.direcoes_retrabalho || selectedCard.resultado_cliente) && (
                                        <div className="rounded-md border border-amber-200 bg-amber-50 p-3 dark:border-amber-900/50 dark:bg-amber-950/20">
                                            <p className="text-xs font-semibold text-amber-800 dark:text-amber-300 mb-2">Retorno Comercial / Cliente</p>
                                            {selectedCard.resultado_cliente && (
                                                <p className="text-xs text-muted-foreground mb-1">Resultado: {selectedCard.resultado_cliente}</p>
                                            )}
                                            {selectedCard.feedback_cliente && (
                                                <p className="text-sm whitespace-pre-wrap"><span className="font-medium">Feedback:</span> {selectedCard.feedback_cliente}</p>
                                            )}
                                            {selectedCard.direcoes_retrabalho && (
                                                <p className="text-sm whitespace-pre-wrap mt-2"><span className="font-medium">Orientações para retrabalho:</span> {selectedCard.direcoes_retrabalho}</p>
                                            )}
                                        </div>
                                    )}
                                    <div>
                                        <p className="text-xs font-semibold text-muted-foreground mb-1">Responsável P&D</p>
                                        <p className="text-sm">{selectedCard.responsavel_pd || 'Não atribuído'}</p>
                                    </div>
                                    {selectedCard.prazo_prometido && (
                                        <div>
                                            <p className="text-xs font-semibold text-muted-foreground mb-1">Prazo Prometido</p>
                                            <p className="text-sm flex items-center gap-1">
                                                <Calendar className="h-3 w-3" />
                                                {new Date(selectedCard.prazo_prometido).toLocaleDateString('pt-BR')}
                                            </p>
                                        </div>
                                    )}
                                    {selectedCard.pd_request_id && (
                                        <Button size="sm" variant="outline" className="w-full gap-1.5" onClick={() => navigate(`/pd/${selectedCard.pd_request_id}`)}>
                                            <ExternalLink className="h-3.5 w-3.5" /> Abrir Detalhes Completos
                                        </Button>
                                    )}
                                </div>
                            </div>
                        </>
                    )}
                </SheetContent>
            </Sheet>

            {/* Nova Pesquisa Interna Dialog */}
            <Dialog open={showResearch} onOpenChange={setShowResearch}>
                <DialogContent className="max-w-2xl">
                    <DialogHeader>
                        <DialogTitle className="flex items-center gap-2">
                            <Sparkles className="h-5 w-5 text-purple-500" /> Nova Pesquisa Interna
                        </DialogTitle>
                        <DialogDescription>
                            Inicie um desenvolvimento de pesquisa própria do lab, sem cliente. O card aparecerá direto em "Em Desenvolvimento".
                        </DialogDescription>
                    </DialogHeader>

                    <div className="grid grid-cols-2 gap-3">
                        <div className="col-span-2">
                            <Label>Nome do Projeto *</Label>
                            <Input
                                value={researchForm.project_name}
                                onChange={(e) => setResearchForm(p => ({ ...p, project_name: e.target.value }))}
                                placeholder="Ex: Estudo de novas bases para body splash"
                            />
                        </div>
                        <div className="col-span-2">
                            <Label>Objetivos da Pesquisa</Label>
                            <Textarea
                                value={researchForm.objectives}
                                onChange={(e) => setResearchForm(p => ({ ...p, objectives: e.target.value }))}
                                rows={3}
                                placeholder="O que se espera descobrir / desenvolver?"
                            />
                        </div>
                        <div className="col-span-2">
                            <Label>Descrição</Label>
                            <Textarea
                                value={researchForm.description}
                                onChange={(e) => setResearchForm(p => ({ ...p, description: e.target.value }))}
                                rows={2}
                                placeholder="Contexto e detalhes"
                            />
                        </div>
                        <div>
                            <Label>Categoria</Label>
                            <Input
                                value={researchForm.category}
                                onChange={(e) => setResearchForm(p => ({ ...p, category: e.target.value }))}
                                placeholder="Ex: Perfumaria, Hidratação..."
                            />
                        </div>
                        <div>
                            <Label>Prioridade</Label>
                            <Select value={researchForm.priority} onValueChange={(v) => setResearchForm(p => ({ ...p, priority: v }))}>
                                <SelectTrigger><SelectValue /></SelectTrigger>
                                <SelectContent>
                                    <SelectItem value="Baixa">Baixa</SelectItem>
                                    <SelectItem value="Normal">Normal</SelectItem>
                                    <SelectItem value="Alta">Alta</SelectItem>
                                    <SelectItem value="Urgente">Urgente</SelectItem>
                                </SelectContent>
                            </Select>
                        </div>
                        <div>
                            <Label>Prazo Alvo</Label>
                            <Input
                                type="date"
                                value={researchForm.deadline}
                                onChange={(e) => setResearchForm(p => ({ ...p, deadline: e.target.value }))}
                            />
                        </div>
                        <div>
                            <Label>Referências</Label>
                            <Input
                                value={researchForm.references}
                                onChange={(e) => setResearchForm(p => ({ ...p, references: e.target.value }))}
                                placeholder="Artigos, produtos similares..."
                            />
                        </div>
                    </div>

                    <DialogFooter>
                        <Button variant="ghost" onClick={() => setShowResearch(false)}>Cancelar</Button>
                        <Button onClick={createInternalResearch} disabled={creatingResearch} className="gap-1.5">
                            <Sparkles className="h-4 w-4" />
                            {creatingResearch ? "Criando..." : "Criar e abrir"}
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        </div>
    );
}
