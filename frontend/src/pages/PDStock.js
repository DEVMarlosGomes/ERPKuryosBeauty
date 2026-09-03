import { useState, useEffect, useCallback, useRef } from "react";
import api from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from "@/components/ui/dialog";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Card, CardContent } from "@/components/ui/card";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Plus, Search, Pencil, Trash2, Package, AlertTriangle, ArrowUpCircle, ArrowDownCircle, Edit3, History, MapPin, Calendar, AlertCircle, Loader2, FlaskConical, X } from "lucide-react";
import { toast } from "sonner";
import PDSubNav from "@/components/PDSubNav";

const CATEGORIAS = [
  { id: "mp", label: "Matérias-Primas", icon: "🧪" },
  { id: "insumo", label: "Insumos", icon: "📦" },
  { id: "amostra_acabada", label: "Amostras Acabadas", icon: "✨" },
];

const emptyForm = {
  categoria: "mp",
  nome: "",
  codigo_interno: "",       // R05: read-only em novos itens, gerado pelo backend
  fragrancia_id: "",        // R09: FR-NNNNN do cadastro de fragrâncias
  unidade_medida: "kg",
  quantidade_atual: "",
  quantidade_minima: "",
  lote: "",
  validade: "",
  localizacao: "",
  custo_unitario: "",
  fornecedor: "",
  observacoes: "",
  catalog_id: "",
  formula_ref: "",
  fragrancia_percentual: "",
};

export default function PDStock() {
  const [activeTab, setActiveTab] = useState("mp");
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [alerts, setAlerts] = useState({ low_stock: [], expiring: [] });
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState(null);
  const [form, setForm] = useState(emptyForm);
  const [saving, setSaving] = useState(false);
  const [catalog, setCatalog] = useState([]);
  const [movementItem, setMovementItem] = useState(null);
  const [moveForm, setMoveForm] = useState({ tipo: "entrada", quantidade: "", motivo: "", lote: "" });
  const [historyItem, setHistoryItem] = useState(null);
  const [movements, setMovements] = useState([]);

  // R09: fragrância search
  const [fragSearch, setFragSearch] = useState("");
  const [fragOptions, setFragOptions] = useState([]);
  const [loadingFrags, setLoadingFrags] = useState(false);
  const [selectedFrag, setSelectedFrag] = useState(null);
  const [showFragDropdown, setShowFragDropdown] = useState(false);
  const fragRef = useRef(null);

  const loadItems = useCallback(async () => {
    setLoading(true);
    try {
      const params = { categoria: activeTab };
      if (search) params.q = search;
      const { data } = await api.get("/pd/stock", { params });
      setItems(Array.isArray(data) ? data : []);
    } catch (e) {
      toast.error("Erro ao carregar estoque");
    } finally {
      setLoading(false);
    }
  }, [activeTab, search]);

  const loadAlerts = useCallback(async () => {
    try {
      const { data } = await api.get("/pd/stock/alerts");
      setAlerts(data || { low_stock: [], expiring: [] });
    } catch (e) { /* silent */ }
  }, []);

  const loadCatalog = useCallback(async () => {
    try {
      const { data } = await api.get("/pd/catalog");
      setCatalog(Array.isArray(data) ? data : []);
    } catch (e) { /* silent */ }
  }, []);

  useEffect(() => { loadItems(); loadAlerts(); }, [loadItems, loadAlerts]);
  useEffect(() => { loadCatalog(); }, [loadCatalog]);

  // R09: busca de fragrâncias com debounce
  useEffect(() => {
    if (!fragSearch.trim() || fragSearch.length < 2) { setFragOptions([]); return; }
    const t = setTimeout(async () => {
      setLoadingFrags(true);
      try {
        const { data } = await api.get("/cadastros/fragrancias", { params: { search: fragSearch } });
        setFragOptions(data.fragrancias || []);
        setShowFragDropdown(true);
      } catch { setFragOptions([]); }
      finally { setLoadingFrags(false); }
    }, 300);
    return () => clearTimeout(t);
  }, [fragSearch]);

  // Fecha dropdown ao clicar fora
  useEffect(() => {
    const handler = (e) => { if (fragRef.current && !fragRef.current.contains(e.target)) setShowFragDropdown(false); };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const openCreate = () => {
    setEditingId(null);
    setSelectedFrag(null);
    setFragSearch("");
    setFragOptions([]);
    setForm({ ...emptyForm, categoria: activeTab });
    setShowForm(true);
  };

  const openEdit = (item) => {
    setEditingId(item.id);
    setSelectedFrag(null);
    setFragSearch("");
    setFragOptions([]);
    setForm({
      categoria: item.categoria,
      nome: item.nome || "",
      codigo_interno: item.codigo_interno || "",
      fragrancia_id: item.fragrancia_id || "",
      unidade_medida: item.unidade_medida || "kg",
      quantidade_atual: String(item.quantidade_atual ?? ""),
      quantidade_minima: String(item.quantidade_minima ?? ""),
      lote: item.lote || "",
      validade: item.validade ? item.validade.slice(0, 10) : "",
      localizacao: item.localizacao || "",
      custo_unitario: String(item.custo_unitario ?? ""),
      fornecedor: item.fornecedor || "",
      observacoes: item.observacoes || "",
      catalog_id: item.catalog_id || "",
      formula_ref: item.formula_ref || "",
      fragrancia_percentual: item.fragrancia_percentual != null ? String(item.fragrancia_percentual) : "",
    });
    setShowForm(true);
  };

  const save = async () => {
    if (!form.nome.trim()) return toast.error("Nome é obrigatório");
    setSaving(true);
    try {
      const payload = {
        ...form,
        quantidade_atual: parseFloat(form.quantidade_atual) || 0,
        quantidade_minima: parseFloat(form.quantidade_minima) || 0,
        custo_unitario: parseFloat(form.custo_unitario) || 0,
        fragrancia_percentual: form.fragrancia_percentual ? parseFloat(form.fragrancia_percentual) : null,
        validade: form.validade || null,
        catalog_id: form.catalog_id || null,
        fragrancia_id: form.fragrancia_id || null,
        // R05: código gerado no backend — não enviar vazio para sobrescrever
        codigo_interno: editingId ? form.codigo_interno : (form.codigo_interno || undefined),
      };
      if (editingId) {
        // remove quantidade_atual from update payload (controlled via movements)
        delete payload.quantidade_atual;
        await api.put(`/pd/stock/${editingId}`, payload);
        toast.success("Item atualizado");
      } else {
        await api.post("/pd/stock", payload);
        toast.success("Item cadastrado");
      }
      setShowForm(false);
      loadItems();
      loadAlerts();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Erro ao salvar");
    } finally {
      setSaving(false);
    }
  };

  const remove = async (id) => {
    if (!window.confirm("Remover este item do estoque? (Movimentações também serão apagadas)")) return;
    try {
      await api.delete(`/pd/stock/${id}`);
      toast.success("Removido");
      loadItems();
      loadAlerts();
    } catch (e) {
      toast.error("Erro ao remover");
    }
  };

  const openMovement = (item, tipo) => {
    setMovementItem(item);
    setMoveForm({ tipo, quantidade: "", motivo: "", lote: item.lote || "" });
  };

  const saveMovement = async () => {
    if (!moveForm.quantidade || parseFloat(moveForm.quantidade) <= 0) {
      return toast.error("Informe uma quantidade válida");
    }
    try {
      await api.post(`/pd/stock/${movementItem.id}/movements`, {
        tipo: moveForm.tipo,
        quantidade: parseFloat(moveForm.quantidade),
        motivo: moveForm.motivo,
        lote: moveForm.lote,
      });
      toast.success("Movimentação registrada");
      setMovementItem(null);
      loadItems();
      loadAlerts();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Erro");
    }
  };

  const openHistory = async (item) => {
    setHistoryItem(item);
    try {
      const { data } = await api.get(`/pd/stock/${item.id}/movements`);
      setMovements(Array.isArray(data) ? data : []);
    } catch (e) { setMovements([]); }
  };

  const totalLowStock = alerts.low_stock?.length || 0;
  const totalExpiring = alerts.expiring?.length || 0;

  return (
    <div className="p-6 page-enter">
      <PDSubNav active="stock" />

      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-3xl font-heading font-semibold tracking-tight flex items-center gap-2">
            <Package className="h-7 w-7 text-primary" /> Estoque do Lab
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            Controle de MPs, Insumos e Amostras Acabadas — com lotes, validade e alertas.
          </p>
        </div>
        <Button onClick={openCreate} className="gap-1.5"><Plus className="h-4 w-4" /> Novo Item</Button>
      </div>

      {(totalLowStock > 0 || totalExpiring > 0) && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mb-4">
          {totalLowStock > 0 && (
            <Card className="border-red-300 bg-red-50 dark:bg-red-950/30">
              <CardContent className="p-3 flex items-center gap-3">
                <AlertTriangle className="h-5 w-5 text-red-500" />
                <div>
                  <p className="font-semibold text-sm">{totalLowStock} item(s) em estoque baixo</p>
                  <p className="text-xs text-muted-foreground">Abaixo do mínimo cadastrado</p>
                </div>
              </CardContent>
            </Card>
          )}
          {totalExpiring > 0 && (
            <Card className="border-amber-300 bg-amber-50 dark:bg-amber-950/30">
              <CardContent className="p-3 flex items-center gap-3">
                <Calendar className="h-5 w-5 text-amber-500" />
                <div>
                  <p className="font-semibold text-sm">{totalExpiring} item(s) vencendo em 30 dias</p>
                  <p className="text-xs text-muted-foreground">Verificar validade</p>
                </div>
              </CardContent>
            </Card>
          )}
        </div>
      )}

      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabsList className="mb-4">
          {CATEGORIAS.map(c => (
            <TabsTrigger key={c.id} value={c.id} className="gap-1.5">
              <span>{c.icon}</span> {c.label}
            </TabsTrigger>
          ))}
        </TabsList>

        <div className="relative mb-4 max-w-md">
          <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input placeholder="Buscar..." value={search} onChange={(e) => setSearch(e.target.value)} className="pl-9" />
        </div>

        {CATEGORIAS.map(c => (
          <TabsContent key={c.id} value={c.id}>
            <StockTable
              items={items}
              loading={loading}
              categoria={c.id}
              onEdit={openEdit}
              onDelete={remove}
              onMovement={openMovement}
              onHistory={openHistory}
            />
          </TabsContent>
        ))}
      </Tabs>

      {/* Create/Edit Dialog */}
      <Dialog open={showForm} onOpenChange={setShowForm}>
        <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{editingId ? "Editar Item do Estoque" : "Novo Item do Estoque"}</DialogTitle>
            <DialogDescription>
              {form.categoria === "amostra_acabada"
                ? "Amostra pronta para envio rápido ao cliente (ex: Body Splash La Vie 3% fragrância)."
                : "Cadastre o item com lote, validade e localização."}
            </DialogDescription>
          </DialogHeader>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label>Categoria *</Label>
              <Select value={form.categoria} onValueChange={(v) => setForm(p => ({ ...p, categoria: v }))}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  {CATEGORIAS.map(c => <SelectItem key={c.id} value={c.id}>{c.label}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label>Código Interno</Label>
              {/* R05: somente leitura em novos itens — gerado pelo backend */}
              {editingId ? (
                <Input value={form.codigo_interno} onChange={(e) => setForm(p => ({ ...p, codigo_interno: e.target.value }))} placeholder="Ex: MP-00001" />
              ) : (
                <div className="flex items-center h-9 px-3 rounded-md border bg-muted/50 text-sm text-muted-foreground gap-2">
                  {form.fragrancia_id
                    ? <><FlaskConical className="h-3.5 w-3.5" /> {form.fragrancia_id}</>
                    : "Gerado automaticamente"
                  }
                </div>
              )}
            </div>

            {/* R09: picker de fragrância (somente em mp, somente no create) */}
            {!editingId && form.categoria === "mp" && (
              <div className="col-span-2" ref={fragRef}>
                <Label>Vincular Fragrância (opcional)</Label>
                <div className="relative mt-1">
                  {selectedFrag ? (
                    <div className="flex items-center gap-2 h-9 px-3 rounded-md border bg-emerald-50 border-emerald-300 text-sm">
                      <FlaskConical className="h-3.5 w-3.5 text-emerald-600" />
                      <span className="font-mono text-emerald-700">{selectedFrag.codigo_interno}</span>
                      <span className="text-emerald-800 truncate">{selectedFrag.inspiracao}</span>
                      {selectedFrag.fornecedores?.[0] && (
                        <span className="ml-auto text-xs text-emerald-600">Cod. fornecedor: {selectedFrag.fornecedores[0].codigo_fornecedor}</span>
                      )}
                      <button type="button" onClick={() => {
                        setSelectedFrag(null);
                        setFragSearch("");
                        setForm(p => ({ ...p, fragrancia_id: "", fornecedor: "" }));
                      }}>
                        <X className="h-3.5 w-3.5 text-emerald-600 hover:text-red-500" />
                      </button>
                    </div>
                  ) : (
                    <div className="relative">
                      <FlaskConical className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
                      <Input
                        className="pl-8"
                        placeholder="Buscar por FR-xxxxx ou inspiração..."
                        value={fragSearch}
                        onChange={(e) => { setFragSearch(e.target.value); setShowFragDropdown(true); }}
                        onFocus={() => fragSearch.length >= 2 && setShowFragDropdown(true)}
                      />
                      {loadingFrags && <Loader2 className="absolute right-2.5 top-2.5 h-4 w-4 animate-spin text-muted-foreground" />}
                    </div>
                  )}
                  {showFragDropdown && fragOptions.length > 0 && !selectedFrag && (
                    <div className="absolute z-50 mt-1 w-full rounded-md border bg-background shadow-lg max-h-52 overflow-y-auto">
                      {fragOptions.map((fr) => (
                        <button
                          key={fr.codigo_interno}
                          type="button"
                          className="w-full text-left px-3 py-2 hover:bg-muted text-sm flex items-center gap-2"
                          onClick={() => {
                            setSelectedFrag(fr);
                            setShowFragDropdown(false);
                            setFragSearch("");
                            const priCodforn = fr.fornecedores?.[0]?.codigo_fornecedor || "";
                            const priFornNome = fr.fornecedores?.[0]?.fornecedor_nome || "";
                            setForm(p => ({
                              ...p,
                              fragrancia_id: fr.codigo_interno,
                              nome: p.nome || fr.inspiracao,
                              fornecedor: p.fornecedor || priFornNome || priCodforn,
                            }));
                          }}
                        >
                          <span className="font-mono text-xs text-primary">{fr.codigo_interno}</span>
                          <span className="flex-1 truncate">{fr.inspiracao}</span>
                          {fr.fornecedores?.[0] && (
                            <span className="text-xs text-muted-foreground shrink-0">{fr.fornecedores[0].codigo_fornecedor}</span>
                          )}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
                {form.fragrancia_id && (
                  <p className="text-xs text-muted-foreground mt-1">
                    Código FR do cadastro será usado como código interno deste item.
                  </p>
                )}
              </div>
            )}

            <div className="col-span-2">
              <Label>Nome *</Label>
              <Input value={form.nome} onChange={(e) => setForm(p => ({ ...p, nome: e.target.value }))} placeholder={form.categoria === "amostra_acabada" ? "Ex: Body Splash La Vie 3% fragrância" : "Ex: Álcool de Cereais 96°"} />
            </div>

            {form.categoria === "mp" && catalog.length > 0 && (
              <div className="col-span-2">
                <Label>Linkar ao Banco de Custos (opcional)</Label>
                <Select value={form.catalog_id || "none"} onValueChange={(v) => {
                  if (v === "none") {
                    setForm(p => ({ ...p, catalog_id: "" }));
                    return;
                  }
                  const cat = catalog.find(c => c.id === v);
                  setForm(p => ({
                    ...p,
                    catalog_id: v,
                    nome: p.nome || cat?.nome || "",
                    fornecedor: p.fornecedor || cat?.fornecedor || "",
                    custo_unitario: p.custo_unitario || String(cat?.preco_rs_kg || ""),
                  }));
                }}>
                  <SelectTrigger><SelectValue placeholder="— Nenhum —" /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="none">— Nenhum —</SelectItem>
                    {catalog.map(c => (
                      <SelectItem key={c.id} value={c.id}>{c.nome} {c.fornecedor ? `(${c.fornecedor})` : ""}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            )}

            {form.categoria === "amostra_acabada" && (
              <>
                <div>
                  <Label>% Fragrância</Label>
                  <Input type="number" step="0.1" value={form.fragrancia_percentual} onChange={(e) => setForm(p => ({ ...p, fragrancia_percentual: e.target.value }))} placeholder="3.0" />
                </div>
                <div>
                  <Label>Referência / Fórmula</Label>
                  <Input value={form.formula_ref} onChange={(e) => setForm(p => ({ ...p, formula_ref: e.target.value }))} placeholder="Ex: Body Splash La Vie v2" />
                </div>
              </>
            )}

            <div>
              <Label>Unidade</Label>
              <Select value={form.unidade_medida} onValueChange={(v) => setForm(p => ({ ...p, unidade_medida: v }))}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="kg">kg</SelectItem>
                  <SelectItem value="g">g</SelectItem>
                  <SelectItem value="L">Litro</SelectItem>
                  <SelectItem value="mL">mL</SelectItem>
                  <SelectItem value="un">unidade</SelectItem>
                </SelectContent>
              </Select>
            </div>
            {!editingId && (
              <div>
                <Label>Quantidade Inicial</Label>
                <Input type="number" step="0.001" value={form.quantidade_atual} onChange={(e) => setForm(p => ({ ...p, quantidade_atual: e.target.value }))} placeholder="0" />
              </div>
            )}
            <div>
              <Label>Quantidade Mínima (alerta)</Label>
              <Input type="number" step="0.001" value={form.quantidade_minima} onChange={(e) => setForm(p => ({ ...p, quantidade_minima: e.target.value }))} placeholder="0" />
            </div>
            <div>
              <Label>Custo Unitário (R$)</Label>
              <Input type="number" step="0.01" value={form.custo_unitario} onChange={(e) => setForm(p => ({ ...p, custo_unitario: e.target.value }))} placeholder="0.00" />
            </div>
            <div>
              <Label>Lote</Label>
              <Input value={form.lote} onChange={(e) => setForm(p => ({ ...p, lote: e.target.value }))} placeholder="Ex: L25-001" />
            </div>
            <div>
              <Label>Validade</Label>
              <Input type="date" value={form.validade} onChange={(e) => setForm(p => ({ ...p, validade: e.target.value }))} />
            </div>
            <div className="col-span-2">
              <Label>Localização</Label>
              <Input value={form.localizacao} onChange={(e) => setForm(p => ({ ...p, localizacao: e.target.value }))} placeholder="Ex: Prateleira A — Gaveta 2" />
            </div>
            <div className="col-span-2">
              <Label>Fornecedor</Label>
              <Input value={form.fornecedor} onChange={(e) => setForm(p => ({ ...p, fornecedor: e.target.value }))} />
            </div>
            <div className="col-span-2">
              <Label>Observações</Label>
              <Textarea value={form.observacoes} onChange={(e) => setForm(p => ({ ...p, observacoes: e.target.value }))} rows={2} />
            </div>
          </div>

          <DialogFooter>
            <Button variant="ghost" onClick={() => setShowForm(false)}>Cancelar</Button>
            <Button onClick={save} disabled={saving}>{saving ? "Salvando..." : (editingId ? "Salvar alterações" : "Cadastrar")}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Movement Dialog */}
      <Dialog open={!!movementItem} onOpenChange={(open) => !open && setMovementItem(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {moveForm.tipo === "entrada" && <>Registrar Entrada</>}
              {moveForm.tipo === "saida" && <>Registrar Saída</>}
              {moveForm.tipo === "ajuste" && <>Ajustar Estoque</>}
            </DialogTitle>
            <DialogDescription>
              {movementItem?.nome} — Estoque atual: <b>{movementItem?.quantidade_atual} {movementItem?.unidade_medida}</b>
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-3">
            <div>
              <Label>{moveForm.tipo === "ajuste" ? "Nova Quantidade (absoluta)" : "Quantidade"}</Label>
              <Input type="number" step="0.001" value={moveForm.quantidade} onChange={(e) => setMoveForm(p => ({ ...p, quantidade: e.target.value }))} placeholder="0" />
            </div>
            <div>
              <Label>Lote</Label>
              <Input value={moveForm.lote} onChange={(e) => setMoveForm(p => ({ ...p, lote: e.target.value }))} />
            </div>
            <div>
              <Label>Motivo / Observação</Label>
              <Textarea value={moveForm.motivo} onChange={(e) => setMoveForm(p => ({ ...p, motivo: e.target.value }))} rows={2} placeholder={moveForm.tipo === "saida" ? "Ex: Usado no desenvolvimento XYZ" : "Ex: Compra, ajuste inventário"} />
            </div>
          </div>

          <DialogFooter>
            <Button variant="ghost" onClick={() => setMovementItem(null)}>Cancelar</Button>
            <Button onClick={saveMovement}>Registrar</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Movement History Sheet */}
      <Sheet open={!!historyItem} onOpenChange={(open) => !open && setHistoryItem(null)}>
        <SheetContent side="right" className="w-[520px] sm:w-[560px] overflow-y-auto">
          <SheetHeader>
            <SheetTitle className="flex items-center gap-2"><History className="h-5 w-5" /> Movimentações</SheetTitle>
          </SheetHeader>
          {historyItem && (
            <div className="mt-6 space-y-4">
              <Card>
                <CardContent className="p-4">
                  <p className="font-semibold">{historyItem.nome}</p>
                  <p className="text-xs text-muted-foreground">{historyItem.codigo_interno || "Sem código"}</p>
                  <p className="text-2xl font-bold mt-2">{historyItem.quantidade_atual} <span className="text-xs font-normal">{historyItem.unidade_medida}</span></p>
                </CardContent>
              </Card>
              <div className="space-y-2">
                {movements.length === 0 ? (
                  <p className="text-sm text-muted-foreground italic">Sem movimentações.</p>
                ) : movements.map(m => (
                  <div key={m.id} className="border rounded-md p-3 text-sm">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        {m.tipo === "entrada" && <ArrowUpCircle className="h-4 w-4 text-green-500" />}
                        {m.tipo === "saida" && <ArrowDownCircle className="h-4 w-4 text-red-500" />}
                        {m.tipo === "ajuste" && <Edit3 className="h-4 w-4 text-blue-500" />}
                        <span className="font-semibold capitalize">{m.tipo}</span>
                        <span className="font-mono">{m.quantidade} {historyItem.unidade_medida}</span>
                      </div>
                      <Badge variant="outline" className="text-[10px]">{m.quantidade_antes ?? "-"} → {m.quantidade_depois}</Badge>
                    </div>
                    {m.motivo && <p className="text-xs mt-1">{m.motivo}</p>}
                    <p className="text-[10px] text-muted-foreground mt-1">
                      {m.user_name || "—"} • {new Date(m.created_at).toLocaleString("pt-BR")}
                      {m.lote && <> • lote {m.lote}</>}
                    </p>
                  </div>
                ))}
              </div>
            </div>
          )}
        </SheetContent>
      </Sheet>
    </div>
  );
}

function StockTable({ items, loading, categoria, onEdit, onDelete, onMovement, onHistory }) {
  return (
    <Card>
      <CardContent className="p-0">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-muted/50 border-b">
                <th className="text-left p-3 font-semibold">Item</th>
                {categoria === "amostra_acabada" && <th className="text-left p-3 font-semibold">% Frag.</th>}
                <th className="text-right p-3 font-semibold w-28">Estoque</th>
                <th className="text-right p-3 font-semibold w-24">Mín.</th>
                <th className="text-left p-3 font-semibold">Lote / Validade</th>
                <th className="text-left p-3 font-semibold">Localização</th>
                <th className="w-48"></th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr><td colSpan={7} className="p-6 text-center text-muted-foreground">Carregando...</td></tr>
              ) : items.length === 0 ? (
                <tr><td colSpan={7} className="p-6 text-center text-muted-foreground">Nenhum item nesta categoria.</td></tr>
              ) : items.map(item => {
                const low = item.quantidade_minima > 0 && item.quantidade_atual <= item.quantidade_minima;
                const expiring = item.validade && (new Date(item.validade) - new Date()) < 30 * 24 * 60 * 60 * 1000;
                return (
                  <tr key={item.id} className={`border-b hover:bg-muted/20 ${low ? "bg-red-50/50 dark:bg-red-950/10" : ""}`}>
                    <td className="p-3">
                      <div className="flex items-center gap-2">
                        {low && <AlertCircle className="h-3.5 w-3.5 text-red-500" />}
                        <div>
                          <div className="font-medium">{item.nome}</div>
                          {item.codigo_interno && <div className="text-[10px] text-muted-foreground">{item.codigo_interno}</div>}
                          {item.fornecedor && <div className="text-[10px] text-muted-foreground">{item.fornecedor}</div>}
                          {item.formula_ref && <div className="text-[10px] text-muted-foreground italic">{item.formula_ref}</div>}
                        </div>
                      </div>
                    </td>
                    {categoria === "amostra_acabada" && (
                      <td className="p-3 text-xs">{item.fragrancia_percentual != null ? `${item.fragrancia_percentual}%` : "—"}</td>
                    )}
                    <td className="p-3 text-right font-mono font-semibold">
                      {item.quantidade_atual} <span className="text-[10px] text-muted-foreground">{item.unidade_medida}</span>
                    </td>
                    <td className="p-3 text-right text-xs text-muted-foreground">
                      {item.quantidade_minima || "—"}
                    </td>
                    <td className="p-3 text-xs">
                      {item.lote ? <div>{item.lote}</div> : <span className="text-muted-foreground">—</span>}
                      {item.validade && (
                        <div className={expiring ? "text-amber-600" : "text-muted-foreground"}>
                          até {new Date(item.validade).toLocaleDateString("pt-BR")}
                        </div>
                      )}
                    </td>
                    <td className="p-3 text-xs">
                      {item.localizacao ? (
                        <span className="flex items-center gap-1"><MapPin className="h-3 w-3" /> {item.localizacao}</span>
                      ) : <span className="text-muted-foreground">—</span>}
                    </td>
                    <td className="p-3">
                      <div className="flex items-center gap-1 justify-end">
                        <Button variant="ghost" size="icon" className="h-7 w-7 hover:text-green-600" title="Entrada" onClick={() => onMovement(item, "entrada")}>
                          <ArrowUpCircle className="h-3.5 w-3.5" />
                        </Button>
                        <Button variant="ghost" size="icon" className="h-7 w-7 hover:text-red-600" title="Saída" onClick={() => onMovement(item, "saida")}>
                          <ArrowDownCircle className="h-3.5 w-3.5" />
                        </Button>
                        <Button variant="ghost" size="icon" className="h-7 w-7" title="Ajuste" onClick={() => onMovement(item, "ajuste")}>
                          <Edit3 className="h-3.5 w-3.5" />
                        </Button>
                        <Button variant="ghost" size="icon" className="h-7 w-7" title="Histórico" onClick={() => onHistory(item)}>
                          <History className="h-3.5 w-3.5" />
                        </Button>
                        <Button variant="ghost" size="icon" className="h-7 w-7" title="Editar" onClick={() => onEdit(item)}>
                          <Pencil className="h-3.5 w-3.5" />
                        </Button>
                        <Button variant="ghost" size="icon" className="h-7 w-7 hover:text-red-500" title="Remover" onClick={() => onDelete(item.id)}>
                          <Trash2 className="h-3.5 w-3.5" />
                        </Button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  );
}
