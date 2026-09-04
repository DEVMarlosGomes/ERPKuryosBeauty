import { useCallback, useEffect, useMemo, useState } from "react";
import api from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Separator } from "@/components/ui/separator";
import {
  Building2,
  CheckCircle2,
  ClipboardList,
  Database,
  Edit3,
  Factory,
  FileText,
  GitBranch,
  Layers3,
  MapPinned,
  Package,
  Plus,
  RefreshCw,
  Search,
  ShieldCheck,
  Tags,
  Trash2,
  Users,
  Warehouse,
  FolderPlus,
} from "lucide-react";
import { toast } from "sonner";

const emptyCliente = {
  nome_empresa: "",
  cnpj: "",
  cli4: "",
  responsavel: "",
  email: "",
  telefone: "",
  cidade: "",
  uf: "",
  segmento: "",
  observacoes: "",
};

const emptyFornecedor = {
  razao_social: "",
  cnpj: "",
  nome_fantasia: "",
  email: "",
  telefone: "",
  categoria: "",
  observacoes: "",
};

const emptyCategoriaMp = {
  catmp3: "",
  nome: "",
  tipo: "mp",
  descricao: "",
  justificativa: "",
};

const emptyCategoriaProduto = {
  cat3: "",
  nome: "",
  justificativa: "",
  status: "pendente",
};

const emptyProduto = {
  nome_produto: "",
  cliente_id: "",
  cat3: "",
  categoria: "",
  volume: "",
  unidade_volume: "ml",
  pd_request_id: "",
  observacoes: "",
};

const emptyMaterial = {
  tipo: "mp",
  nome: "",
  categoria_mp_id: "",
  subtipo: "",
  unidade_estoque: "kg",
  unidade_compra: "kg",
  fator_conversao: 1,
  fornecedor_id: "",
  observacoes: "",
};

const emptyEndereco = {
  rua: "",
  modulo: "",
  nivel: "",
  posicao: "",
  area: "Almoxarifado",
  capacidade_paletes: "",
  temperatura: "Ambiente",
  status: "ativo",
};

const emptyProductTech = {
  produto_id: "",
  produto_nome: "",
  formula: [{ material_id: "", material_nome: "", fase: "A", percentual: "", funcao: "" }],
  bom: [{ material_id: "", material_nome: "", quantidade: "", unidade: "un", etapa: "" }],
  especificacoes_tecnicas: {
    aspecto: "",
    cor: "",
    odor: "",
    ph: "",
    densidade: "",
    viscosidade: "",
    validade: "",
    embalagem: "",
    observacoes: "",
  },
  enderecamento: emptyEndereco,
};

const emptyProjeto = {
  cliente_id: "",
  nome_projeto: "",
  categoria: "",
  briefing_resumido: "",
  responsavel_comercial: "",
  prazo_desejado_amostra: "",
  observacoes_livres: "",
};

function StatCard({ icon: Icon, label, value, hint }) {
  return (
    <Card className="rounded-lg">
      <CardContent className="p-4">
        <div className="flex items-center justify-between gap-3">
          <div>
            <p className="text-xs uppercase text-muted-foreground">{label}</p>
            <p className="mt-1 text-2xl font-semibold mono-num">{value ?? 0}</p>
            {hint && <p className="mt-1 text-xs text-muted-foreground">{hint}</p>}
          </div>
          <div className="flex h-10 w-10 items-center justify-center rounded-md bg-primary/10 text-primary">
            <Icon className="h-5 w-5" />
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

function StatusBadge({ value }) {
  const normalized = value || "ativo";
  const cls = {
    ativo: "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300",
    ativa: "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300",
    pendente: "bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300",
    inativo: "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300",
    inativa: "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300",
    suspenso: "bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300",
    homologado: "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300",
    nao_iniciada: "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300",
  }[normalized] || "bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300";
  return <Badge className={`${cls} border-0`}>{String(normalized).replaceAll("_", " ")}</Badge>;
}

function SearchBar({ value, onChange, onRefresh, placeholder = "Buscar..." }) {
  return (
    <div className="flex flex-col gap-2 sm:flex-row">
      <div className="relative flex-1">
        <Search className="absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
        <Input className="pl-9" value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} />
      </div>
      <Button variant="outline" onClick={onRefresh} className="gap-2">
        <RefreshCw className="h-4 w-4" />
        Atualizar
      </Button>
    </div>
  );
}

function ResponsiveTable({ columns, rows, getKey, emptyText }) {
  return (
    <>
      <div className="hidden overflow-x-auto rounded-lg border md:block">
        <Table>
          <TableHeader>
            <TableRow>
              {columns.map((c) => <TableHead key={c.key}>{c.label}</TableHead>)}
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((row) => (
              <TableRow key={getKey(row)}>
                {columns.map((c) => <TableCell key={c.key}>{c.render ? c.render(row) : row[c.key]}</TableCell>)}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
      <div className="grid gap-3 md:hidden">
        {rows.map((row) => (
          <Card key={getKey(row)} className="rounded-lg">
            <CardContent className="space-y-2 p-4">
              {columns.map((c) => (
                <div key={c.key} className="flex items-start justify-between gap-4">
                  <span className="text-xs text-muted-foreground">{c.label}</span>
                  <div className="max-w-[65%] text-right text-sm font-medium">{c.render ? c.render(row) : row[c.key]}</div>
                </div>
              ))}
            </CardContent>
          </Card>
        ))}
      </div>
      {!rows.length && (
        <div className="rounded-lg border border-dashed p-8 text-center text-sm text-muted-foreground">{emptyText}</div>
      )}
    </>
  );
}

function Field({ label, children }) {
  return (
    <div className="space-y-1.5">
      <Label className="text-xs text-muted-foreground">{label}</Label>
      {children}
    </div>
  );
}

function FlowCard({ icon: Icon, title, description, meta, tone = "primary" }) {
  const tones = {
    primary: "bg-primary/10 text-primary",
    success: "bg-emerald-500/10 text-emerald-600 dark:text-emerald-300",
    warning: "bg-amber-500/10 text-amber-600 dark:text-amber-300",
    muted: "bg-muted text-muted-foreground",
  };
  return (
    <Card className="rounded-lg">
      <CardContent className="flex h-full gap-3 p-4">
        <div className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-md ${tones[tone] || tones.primary}`}>
          <Icon className="h-5 w-5" />
        </div>
        <div className="min-w-0">
          <h3 className="font-semibold">{title}</h3>
          <p className="mt-1 text-sm text-muted-foreground">{description}</p>
          {meta && <p className="mt-3 text-xs font-medium uppercase text-muted-foreground">{meta}</p>}
        </div>
      </CardContent>
    </Card>
  );
}

function CadastroDialog({ title, open, onOpenChange, onSubmit, saving, children }) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[92vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
        </DialogHeader>
        <div className="grid gap-4">{children}</div>
        <DialogFooter className="flex-col gap-2 sm:flex-row">
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancelar</Button>
          <Button onClick={onSubmit} disabled={saving} className="gap-2">
            {saving && <RefreshCw className="h-4 w-4 animate-spin" />}
            Salvar
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function RowActions({ onEdit, onDelete, extra }) {
  return (
    <div className="flex flex-wrap justify-end gap-2">
      {extra}
      <Button size="sm" variant="outline" onClick={onEdit} className="gap-1">
        <Edit3 className="h-3.5 w-3.5" />
        Editar
      </Button>
      <Button size="sm" variant="outline" onClick={onDelete} className="gap-1 text-destructive hover:text-destructive">
        <Trash2 className="h-3.5 w-3.5" />
        Excluir
      </Button>
    </div>
  );
}

function formatEndereco(endereco = {}) {
  const parts = [endereco.rua, endereco.modulo, endereco.nivel, endereco.posicao].filter(Boolean);
  return parts.length ? parts.join(" / ") : "Sem endereco";
}

function completionLabel(row, key) {
  const value = row?.[key];
  if (Array.isArray(value)) return value.length ? `${value.length} itens` : "Pendente";
  if (value && typeof value === "object") return Object.values(value).some(Boolean) ? "Completo" : "Pendente";
  return value ? "Completo" : "Pendente";
}

export default function CadastrosPage() {
  const [tab, setTab] = useState("dashboard");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [search, setSearch] = useState("");
  const [dashboard, setDashboard] = useState(null);
  const [clientes, setClientes] = useState([]);
  const [fornecedores, setFornecedores] = useState([]);
  const [produtos, setProdutos] = useState([]);
  const [materiais, setMateriais] = useState([]);
  const [categoriasProduto, setCategoriasProduto] = useState([]);
  const [categoriasMp, setCategoriasMp] = useState([]);
  const [dialog, setDialog] = useState(null);
  const [clienteForm, setClienteForm] = useState(emptyCliente);
  const [fornecedorForm, setFornecedorForm] = useState(emptyFornecedor);
  const [categoriaProdutoForm, setCategoriaProdutoForm] = useState(emptyCategoriaProduto);
  const [categoriaMpForm, setCategoriaMpForm] = useState(emptyCategoriaMp);
  const [produtoForm, setProdutoForm] = useState(emptyProduto);
  const [materialForm, setMaterialForm] = useState(emptyMaterial);
  const [projetoForm, setProjetoForm] = useState(emptyProjeto);
  const [editing, setEditing] = useState({ kind: null, id: null });
  const [productTechForm, setProductTechForm] = useState(emptyProductTech);

  const loadAll = useCallback(async () => {
    setLoading(true);
    try {
      const [dash, cli, forn, prod, mats, catProd, catMp] = await Promise.all([
        api.get("/cadastros/dashboard"),
        api.get("/cadastros/clientes"),
        api.get("/cadastros/fornecedores"),
        api.get("/cadastros/produtos"),
        api.get("/cadastros/materiais-cadastro"),
        api.get("/cadastros/categorias"),
        api.get("/cadastros/categorias-mp"),
      ]);
      setDashboard(dash.data);
      setClientes(cli.data.clientes || []);
      setFornecedores(forn.data.fornecedores || []);
      setProdutos(prod.data.produtos || []);
      setMateriais(mats.data.materiais || []);
      setCategoriasProduto(catProd.data.categorias || []);
      setCategoriasMp(catMp.data.categorias || []);
    } catch (error) {
      toast.error(error.response?.data?.detail || "Erro ao carregar cadastros");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadAll(); }, [loadAll]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    const has = (obj, fields) => !q || fields.some((f) => String(obj[f] || "").toLowerCase().includes(q));
    return {
      clientes: clientes.filter((c) => has(c, ["nome_empresa", "cnpj", "cli4", "responsavel"])),
      fornecedores: fornecedores.filter((f) => has(f, ["razao_social", "nome_fantasia", "cnpj", "codigo_interno"])),
      produtos: produtos.filter((p) => has(p, ["codigo_interno", "nome_produto", "cliente_nome", "categoria"])),
      materiais: materiais.filter((m) => has(m, ["codigo_interno", "nome", "subtipo", "tipo2"])),
      categoriasProduto: categoriasProduto.filter((c) => has(c, ["cat3", "nome", "status"])),
      categoriasMp: categoriasMp.filter((c) => has(c, ["catmp3", "nome", "tipo", "status"])),
    };
  }, [search, clientes, fornecedores, produtos, materiais, categoriasProduto, categoriasMp]);

  const produtosComSku = produtos.filter((p) => p.codigo_interno).length;
  const produtosComPd = produtos.filter((p) => p.pd_concluido || p.pd_request_id).length;
  const materiaisHomologados = materiais.filter((m) => ["homologado", "homologada", "ativo", "ativa"].includes(String(m.status || "").toLowerCase())).length;

  const resetEditing = () => setEditing({ kind: null, id: null });

  const openEntityDialog = (kind, row = null) => {
    setEditing(row ? { kind, id: row.id } : { kind: null, id: null });
    if (kind === "cliente") {
      setClienteForm(row ? { ...emptyCliente, ...row } : emptyCliente);
    }
    if (kind === "fornecedor") {
      setFornecedorForm(row ? {
        ...emptyFornecedor,
        ...row,
        categoria: row.categoria || (row.categorias || [])[0] || "",
        email: row.email || (row.contatos || [])[0]?.email || "",
        telefone: row.telefone || (row.contatos || [])[0]?.telefone || "",
      } : emptyFornecedor);
    }
    if (kind === "categoriaProduto") {
      setCategoriaProdutoForm(row ? { ...emptyCategoriaProduto, ...row } : emptyCategoriaProduto);
    }
    if (kind === "categoriaMp") {
      setCategoriaMpForm(row ? { ...emptyCategoriaMp, ...row } : emptyCategoriaMp);
    }
    if (kind === "produto") {
      setProdutoForm(row ? {
        ...emptyProduto,
        ...row,
        cliente_id: row.cliente_id || "",
        volume: row.volume ?? "",
      } : emptyProduto);
    }
    if (kind === "material") {
      const fornecedor = (row?.fornecedores || [])[0] || {};
      setMaterialForm(row ? {
        ...emptyMaterial,
        ...row,
        tipo: row.tipo || row.tipo2 || "mp",
        categoria_mp_id: row.categoria_mp_id || "",
        fornecedor_id: fornecedor.fornecedor_id || "",
        observacoes: row.observacoes || row.descricao || "",
      } : emptyMaterial);
    }
    setDialog(kind);
  };

  const closeDialog = () => {
    setDialog(null);
    resetEditing();
  };

  const openTechDialog = (produto) => {
    setProductTechForm({
      produto_id: produto.id,
      produto_nome: produto.nome_produto,
      formula: produto.formula?.length ? produto.formula : emptyProductTech.formula,
      bom: produto.bom?.length ? produto.bom : emptyProductTech.bom,
      especificacoes_tecnicas: { ...emptyProductTech.especificacoes_tecnicas, ...(produto.especificacoes_tecnicas || {}) },
      enderecamento: { ...emptyEndereco, ...(produto.enderecamento || {}) },
    });
    setDialog("produtoTecnico");
  };

  const inactivateEntity = async (kind, row) => {
    if ((!row?.id && kind !== "categoriaProduto") || !window.confirm(`Inativar ${row.nome_empresa || row.razao_social || row.nome_produto || row.nome || row.cat3 || row.catmp3}?`)) return;
    const endpoints = {
      cliente: `/cadastros/clientes/${row.id}`,
      fornecedor: `/cadastros/fornecedores/${row.id}`,
      produto: `/cadastros/produtos/${row.id}`,
      material: `/cadastros/materiais-cadastro/${row.id}`,
      categoriaProduto: `/cadastros/categorias/${row.cat3}`,
      categoriaMp: `/cadastros/categorias-mp/${row.id}`,
    };
    try {
      if (kind === "categoriaProduto") await api.post(`/cadastros/categorias/${row.cat3}/inactivate`);
      else await api.delete(endpoints[kind]);
      toast.success("Registro inativado");
      await loadAll();
    } catch (error) {
      toast.error(error.response?.data?.detail || "Erro ao inativar registro");
    }
  };

  const submit = async (kind) => {
    setSaving(true);
    try {
      const isEditing = editing.kind === kind && editing.id;
      if (kind === "cliente") {
        if (isEditing) await api.put(`/cadastros/clientes/${editing.id}`, clienteForm);
        else await api.post("/cadastros/clientes", clienteForm);
        setClienteForm(emptyCliente);
      }
      if (kind === "fornecedor") {
        const payload = isEditing ? {
          razao_social: fornecedorForm.razao_social,
          nome_fantasia: fornecedorForm.nome_fantasia,
          email: fornecedorForm.email,
          telefone: fornecedorForm.telefone,
          categoria: fornecedorForm.categoria,
          observacoes: fornecedorForm.observacoes,
          status_cadastro: fornecedorForm.status_cadastro,
        } : fornecedorForm;
        if (isEditing) await api.put(`/cadastros/fornecedores/${editing.id}`, payload);
        else await api.post("/cadastros/fornecedores", payload);
        setFornecedorForm(emptyFornecedor);
      }
      if (kind === "categoriaProduto") {
        const payload = isEditing ? {
          nome: categoriaProdutoForm.nome,
          justificativa: categoriaProdutoForm.justificativa,
          status: categoriaProdutoForm.status,
        } : {
          cat3: categoriaProdutoForm.cat3,
          nome: categoriaProdutoForm.nome,
          justificativa: categoriaProdutoForm.justificativa,
        };
        if (isEditing) await api.put(`/cadastros/categorias/${categoriaProdutoForm.cat3}`, payload);
        else await api.post("/cadastros/categorias", payload);
        setCategoriaProdutoForm(emptyCategoriaProduto);
      }
      if (kind === "categoriaMp") {
        const payload = isEditing ? {
          nome: categoriaMpForm.nome,
          tipo: categoriaMpForm.tipo,
          descricao: categoriaMpForm.descricao,
          status: categoriaMpForm.status,
        } : categoriaMpForm;
        if (isEditing) await api.put(`/cadastros/categorias-mp/${editing.id}`, payload);
        else await api.post("/cadastros/categorias-mp", payload);
        setCategoriaMpForm(emptyCategoriaMp);
      }
      if (kind === "produto") {
        const payload = {
          ...produtoForm,
          volume: produtoForm.volume === "" ? null : Number(produtoForm.volume),
        };
        if (isEditing) {
          await api.put(`/cadastros/produtos/${editing.id}`, {
            nome_produto: payload.nome_produto,
            categoria: payload.categoria,
            volume: payload.volume,
            unidade_volume: payload.unidade_volume,
            pd_request_id: payload.pd_request_id,
            observacoes: payload.observacoes,
            status: payload.status,
          });
        } else {
          await api.post("/cadastros/produtos", payload);
        }
        setProdutoForm(emptyProduto);
      }
      if (kind === "material") {
        if (isEditing) await api.put(`/cadastros/materiais-cadastro/${editing.id}`, materialForm);
        else await api.post("/cadastros/materiais-cadastro", materialForm);
        setMaterialForm(emptyMaterial);
      }
      if (kind === "produtoTecnico") {
        const cleanFormula = productTechForm.formula
          .filter((item) => item.material_id || item.material_nome || item.percentual)
          .map((item) => ({
            ...item,
            material_nome: item.material_nome || materiais.find((m) => m.id === item.material_id)?.nome || "",
            percentual: item.percentual === "" ? null : Number(item.percentual),
          }));
        const cleanBom = productTechForm.bom
          .filter((item) => item.material_id || item.material_nome || item.quantidade)
          .map((item) => ({
            ...item,
            material_nome: item.material_nome || materiais.find((m) => m.id === item.material_id)?.nome || "",
            quantidade: item.quantidade === "" ? null : Number(item.quantidade),
          }));
        await api.put(`/cadastros/produtos/${productTechForm.produto_id}`, {
          formula: cleanFormula,
          bom: cleanBom,
          especificacoes_tecnicas: productTechForm.especificacoes_tecnicas,
          enderecamento: productTechForm.enderecamento,
        });
        setProductTechForm(emptyProductTech);
      }
      if (kind === "projeto") {
        await api.post("/crm/projects/batch", {
          cliente_id: projetoForm.cliente_id,
          projects: [{
            nome_projeto: projetoForm.nome_projeto,
            categoria: projetoForm.categoria,
            briefing_resumido: projetoForm.briefing_resumido,
            responsavel_comercial: projetoForm.responsavel_comercial,
            prazo_desejado_amostra: projetoForm.prazo_desejado_amostra,
            observacoes_livres: projetoForm.observacoes_livres,
          }],
        });
        setProjetoForm(emptyProjeto);
      }
      toast.success("Cadastro salvo");
      closeDialog();
      await loadAll();
    } catch (error) {
      toast.error(error.response?.data?.detail || "Erro ao salvar cadastro");
    } finally {
      setSaving(false);
    }
  };

  const approveCategoriaMp = async (id) => {
    try {
      await api.post(`/cadastros/categorias-mp/${id}/aprovar`);
      toast.success("Categoria aprovada");
      await loadAll();
    } catch (error) {
      toast.error(error.response?.data?.detail || "Erro ao aprovar");
    }
  };

  const approveCategoriaProduto = async (cat3) => {
    try {
      await api.post(`/cadastros/categorias/${cat3}/approve`, { justificativa: "Aprovado pelo modulo Cadastros" });
      toast.success("Categoria aprovada");
      await loadAll();
    } catch (error) {
      toast.error(error.response?.data?.detail || "Erro ao aprovar categoria");
    }
  };

  const openProjetoDialog = (cliente) => {
    setProjetoForm({
      ...emptyProjeto,
      cliente_id: cliente?.id || "",
      responsavel_comercial: cliente?.responsavel_comercial || "",
    });
    setDialog("projeto");
  };

  const activeCategoriasProduto = categoriasProduto.filter((c) => c.status === "ativa");
  const activeCategoriasMp = categoriasMp.filter((c) => c.status === "ativa");

  return (
    <div className="mx-auto flex w-full max-w-7xl flex-col gap-5 p-4 sm:p-6">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <p className="text-xs uppercase tracking-wide text-muted-foreground">ERP Kuryos</p>
          <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">Modulo Cadastros</h1>
          <p className="mt-1 max-w-3xl text-sm text-muted-foreground">
            Fonte unica para clientes, fornecedores, produtos, materiais e categorias que alimentam P&D, Pedidos, PCP, Compras e Estoque.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button onClick={() => openEntityDialog("cliente")} className="gap-2"><Plus className="h-4 w-4" /> Cliente</Button>
          <Button variant="outline" onClick={() => setDialog("projeto")} className="gap-2"><FolderPlus className="h-4 w-4" /> Projeto</Button>
          <Button variant="outline" onClick={() => openEntityDialog("fornecedor")} className="gap-2"><Plus className="h-4 w-4" /> Fornecedor</Button>
          <Button variant="outline" onClick={() => openEntityDialog("produto")} className="gap-2"><Plus className="h-4 w-4" /> Produto</Button>
          <Button variant="outline" onClick={() => openEntityDialog("material")} className="gap-2"><Plus className="h-4 w-4" /> Material</Button>
        </div>
      </div>

      <SearchBar value={search} onChange={setSearch} onRefresh={loadAll} placeholder="Buscar por SKU, cliente, fornecedor, CNPJ ou categoria..." />

      <Tabs value={tab} onValueChange={setTab} className="w-full">
        <TabsList className="grid h-auto grid-cols-2 gap-1 sm:grid-cols-3 lg:grid-cols-10">
          <TabsTrigger value="dashboard">Visao</TabsTrigger>
          <TabsTrigger value="clientes">Clientes</TabsTrigger>
          <TabsTrigger value="fornecedores">Fornecedores</TabsTrigger>
          <TabsTrigger value="produtos">Produtos</TabsTrigger>
          <TabsTrigger value="materiais">MPs/Insumos</TabsTrigger>
          <TabsTrigger value="engenharia">Formulas/BOM</TabsTrigger>
          <TabsTrigger value="fichas">Fichas</TabsTrigger>
          <TabsTrigger value="enderecos">Enderecos</TabsTrigger>
          <TabsTrigger value="categorias">Categorias</TabsTrigger>
          <TabsTrigger value="integracoes">Integracoes</TabsTrigger>
        </TabsList>

        <TabsContent value="dashboard" className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
            <StatCard icon={Users} label="Clientes" value={dashboard?.totais?.clientes} />
            <StatCard icon={Building2} label="Fornecedores" value={dashboard?.totais?.fornecedores} />
            <StatCard icon={Package} label="Produtos" value={dashboard?.totais?.produtos} />
            <StatCard icon={Warehouse} label="Materiais" value={dashboard?.totais?.materiais} />
            <StatCard icon={Tags} label="Cat. Produto" value={dashboard?.totais?.categorias_produto} />
            <StatCard icon={Layers3} label="Cat. MP" value={dashboard?.totais?.categorias_mp} />
          </div>
          <Card className="rounded-lg">
            <CardHeader><CardTitle className="text-base">Pendencias de governanca</CardTitle></CardHeader>
            <CardContent className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              {Object.entries(dashboard?.pendencias || {}).map(([key, value]) => (
                <div key={key} className="rounded-lg border p-3">
                  <p className="text-xs uppercase text-muted-foreground">{key.replaceAll("_", " ")}</p>
                  <p className="mt-1 text-xl font-semibold mono-num">{value}</p>
                </div>
              ))}
            </CardContent>
          </Card>
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
            <FlowCard
              icon={GitBranch}
              title="SKU e produto final"
              description="Produto aprovado pelo P&D entra aqui com categoria CAT3, cliente CLI4 e sequencial congelado para alimentar pedidos e PCP."
              meta={`${produtosComSku}/${produtos.length} com SKU`}
            />
            <FlowCard
              icon={ClipboardList}
              title="Engenharia do produto"
              description="Aba de formula, BOM de embalagem e ficha tecnica amarra produto acabado, MPs, insumos e materiais de apoio."
              meta={`${produtosComPd}/${produtos.length} vinculados ao P&D`}
              tone="success"
            />
            <FlowCard
              icon={ShieldCheck}
              title="Homologacao unica"
              description="Materiais e fornecedores devem sair de homologacoes para Cadastros, Compras, Banco de Custos e Estoque sem nova digitacao."
              meta={`${materiaisHomologados}/${materiais.length} materiais ativos`}
              tone="warning"
            />
            <FlowCard
              icon={MapPinned}
              title="Enderecamento WMS"
              description="Materiais cadastrados carregam unidade, categoria, fornecedor e endereco preferencial para recebimento e armazenagem."
              meta="base para estoque/lote"
              tone="muted"
            />
          </div>
        </TabsContent>

        <TabsContent value="clientes">
          <ResponsiveTable
            rows={filtered.clientes}
            getKey={(r) => r.id}
            emptyText={loading ? "Carregando..." : "Nenhum cliente encontrado."}
            columns={[
              { key: "nome_empresa", label: "Cliente" },
              { key: "cli4", label: "CLI4", render: (r) => <span className="font-mono">{r.cli4 || "-"}</span> },
              { key: "cnpj", label: "CNPJ" },
              { key: "responsavel", label: "Responsavel" },
              { key: "status_cadastro", label: "Status", render: (r) => <StatusBadge value={r.status_cadastro} /> },
              { key: "acao", label: "Acao", render: (r) => (
                <RowActions
                  onEdit={() => openEntityDialog("cliente", r)}
                  onDelete={() => inactivateEntity("cliente", r)}
                  extra={<Button size="sm" variant="outline" onClick={() => openProjetoDialog(r)} className="gap-1"><FolderPlus className="h-3.5 w-3.5" /> Projeto</Button>}
                />
              ) },
            ]}
          />
        </TabsContent>

        <TabsContent value="fornecedores">
          <ResponsiveTable
            rows={filtered.fornecedores}
            getKey={(r) => r.id}
            emptyText={loading ? "Carregando..." : "Nenhum fornecedor encontrado."}
            columns={[
              { key: "codigo_interno", label: "Codigo", render: (r) => <span className="font-mono">{r.codigo_interno}</span> },
              { key: "razao_social", label: "Fornecedor" },
              { key: "cnpj", label: "CNPJ" },
              { key: "status_homologacao", label: "Homologacao", render: (r) => <StatusBadge value={r.status_homologacao} /> },
              { key: "status_cadastro", label: "Status", render: (r) => <StatusBadge value={r.status_cadastro} /> },
              { key: "acao", label: "Acao", render: (r) => <RowActions onEdit={() => openEntityDialog("fornecedor", r)} onDelete={() => inactivateEntity("fornecedor", r)} /> },
            ]}
          />
        </TabsContent>

        <TabsContent value="produtos">
          <ResponsiveTable
            rows={filtered.produtos}
            getKey={(r) => r.id}
            emptyText={loading ? "Carregando..." : "Nenhum produto encontrado."}
            columns={[
              { key: "codigo_interno", label: "SKU", render: (r) => <span className="font-mono">{r.codigo_interno}</span> },
              { key: "nome_produto", label: "Produto" },
              { key: "cliente_nome", label: "Cliente" },
              { key: "categoria", label: "Categoria" },
              { key: "pd_concluido", label: "P&D", render: (r) => r.pd_concluido ? <StatusBadge value="ativo" /> : <StatusBadge value="pendente" /> },
              { key: "status", label: "Status", render: (r) => <StatusBadge value={r.status} /> },
              { key: "acao", label: "Acao", render: (r) => (
                <RowActions
                  onEdit={() => openEntityDialog("produto", r)}
                  onDelete={() => inactivateEntity("produto", r)}
                  extra={<Button size="sm" variant="outline" onClick={() => openTechDialog(r)} className="gap-1"><ClipboardList className="h-3.5 w-3.5" /> Tecnico</Button>}
                />
              ) },
            ]}
          />
        </TabsContent>

        <TabsContent value="materiais">
          <ResponsiveTable
            rows={filtered.materiais}
            getKey={(r) => r.id}
            emptyText={loading ? "Carregando..." : "Nenhum material encontrado."}
            columns={[
              { key: "codigo_interno", label: "Codigo", render: (r) => <span className="font-mono">{r.codigo_interno}</span> },
              { key: "nome", label: "Material" },
              { key: "tipo2", label: "Tipo" },
              { key: "categoria_mp_nome", label: "Categoria" },
              { key: "unidade_estoque", label: "Un." },
              { key: "status", label: "Status", render: (r) => <StatusBadge value={r.status} /> },
              { key: "acao", label: "Acao", render: (r) => <RowActions onEdit={() => openEntityDialog("material", r)} onDelete={() => inactivateEntity("material", r)} /> },
            ]}
          />
        </TabsContent>

        <TabsContent value="engenharia" className="space-y-4">
          <div className="grid gap-3 lg:grid-cols-3">
            <FlowCard icon={Factory} title="Produto final" description="Cadastro mestre do SKU comercial, cliente, categoria, volume e status de venda." meta={`${produtos.length} produtos`} />
            <FlowCard icon={Database} title="Formula / granel" description="Base tecnica do P&D para variacoes com mesma base, alterando apenas cor, ativo e fragrancia quando permitido." meta="base tecnica" tone="success" />
            <FlowCard icon={Package} title="BOM de embalagem" description="Lista estruturada de frasco, tampa, valvula, rotulo, caixa e demais insumos que Compras e PCP usam no MRP." meta={`${materiais.length} materiais`} tone="warning" />
          </div>
          <ResponsiveTable
            rows={filtered.produtos}
            getKey={(r) => r.id}
            emptyText={loading ? "Carregando..." : "Nenhum produto para engenharia."}
            columns={[
              { key: "codigo_interno", label: "SKU", render: (r) => <span className="font-mono">{r.codigo_interno || "A definir"}</span> },
              { key: "nome_produto", label: "Produto" },
              { key: "cliente_nome", label: "Cliente" },
              { key: "formula", label: "Formula", render: (r) => <Badge variant="outline">{completionLabel(r, "formula")}</Badge> },
              { key: "bom", label: "BOM", render: (r) => <Badge variant="outline">{completionLabel(r, "bom")}</Badge> },
              { key: "especificacoes_tecnicas", label: "Ficha", render: (r) => <StatusBadge value={completionLabel(r, "especificacoes_tecnicas") === "Completo" ? "ativo" : "pendente"} /> },
              { key: "enderecamento", label: "Endereco", render: (r) => <span className="text-sm">{formatEndereco(r.enderecamento)}</span> },
              { key: "acao", label: "Acao", render: (r) => <Button size="sm" onClick={() => openTechDialog(r)} className="gap-1"><ClipboardList className="h-3.5 w-3.5" /> Editar tecnico</Button> },
            ]}
          />
        </TabsContent>

        <TabsContent value="fichas" className="space-y-4">
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
            <FlowCard icon={FileText} title="Ficha tecnica" description="Dados automaticos vindos de SKU, formula, BOM, cliente, volume e categoria." meta="documento mestre" />
            <FlowCard icon={ShieldCheck} title="Qualidade" description="Status de homologacao, restricoes, validade e aprovacao tecnica devem bloquear uso indevido." meta="gate CQ" tone="success" />
            <FlowCard icon={Warehouse} title="Estoque/WMS" description="Unidade, fator de conversao, lote e endereco preferencial alimentam recebimento e consumo." meta="rastreabilidade" tone="warning" />
            <FlowCard icon={Building2} title="Comercial" description="Pedido puxa cliente, CNPJ, endereco, e-mail e SKU aprovado sem redigitar." meta="pedido direto" tone="muted" />
          </div>
          <Card className="rounded-lg">
            <CardHeader><CardTitle className="text-base">Fila de fichas tecnicas</CardTitle></CardHeader>
            <CardContent>
              <ResponsiveTable
                rows={filtered.produtos}
                getKey={(r) => r.id}
                emptyText="Nenhuma ficha pendente."
                columns={[
                  { key: "codigo_interno", label: "SKU", render: (r) => <span className="font-mono">{r.codigo_interno || "A definir"}</span> },
                  { key: "nome_produto", label: "Produto" },
                  { key: "cliente_nome", label: "Cliente" },
                  { key: "categoria", label: "Categoria" },
                  { key: "dados", label: "Dados automaticos", render: (r) => r.codigo_interno && r.cliente_nome && r.formula?.length && r.bom?.length ? <StatusBadge value="ativo" /> : <StatusBadge value="pendente" /> },
                  { key: "ph", label: "pH", render: (r) => r.especificacoes_tecnicas?.ph || "-" },
                  { key: "validade", label: "Validade", render: (r) => r.especificacoes_tecnicas?.validade || "-" },
                  { key: "acao", label: "Acao", render: (r) => <Button size="sm" variant="outline" onClick={() => openTechDialog(r)}>Revisar</Button> },
                ]}
              />
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="enderecos" className="space-y-4">
          <div className="grid gap-3 lg:grid-cols-3">
            <FlowCard icon={MapPinned} title="Rua / modulo / nivel / posicao" description="Estrutura padrao para recebimento, armazenagem, reserva e expedicao no WMS." meta="enderecamento mestre" />
            <FlowCard icon={Warehouse} title="Materiais" description="MPs, insumos e embalagens carregam endereco preferencial para entrada em estoque." meta={`${materiais.filter((m) => Object.values(m.enderecamento || {}).some(Boolean)).length}/${materiais.length} enderecados`} tone="success" />
            <FlowCard icon={Package} title="Produto acabado" description="SKU final mantem endereco sugerido para picking, expedicao e inventario." meta={`${produtos.filter((p) => Object.values(p.enderecamento || {}).some(Boolean)).length}/${produtos.length} enderecados`} tone="warning" />
          </div>
          <Card className="rounded-lg">
            <CardHeader><CardTitle className="text-base">Mapa visual de armazenagem</CardTitle></CardHeader>
            <CardContent>
              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                {[...filtered.produtos.slice(0, 8), ...filtered.materiais.slice(0, 8)].map((item) => {
                  const isProduto = Boolean(item.nome_produto);
                  const endereco = item.enderecamento || {};
                  return (
                    <div key={`${isProduto ? "p" : "m"}-${item.id}`} className="rounded-lg border bg-card p-3 shadow-sm">
                      <div className="mb-3 flex items-start justify-between gap-2">
                        <div className="min-w-0">
                          <p className="truncate text-sm font-semibold">{item.nome_produto || item.nome}</p>
                          <p className="text-xs text-muted-foreground">{item.codigo_interno || item.tipo2 || "Sem codigo"}</p>
                        </div>
                        <Badge variant="outline">{isProduto ? "PA" : item.tipo2 || "MAT"}</Badge>
                      </div>
                      <div className="grid grid-cols-4 gap-2 text-center">
                        {["rua", "modulo", "nivel", "posicao"].map((field) => (
                          <div key={field} className="rounded-md border bg-muted/40 p-2">
                            <p className="text-[10px] uppercase text-muted-foreground">{field}</p>
                            <p className="font-mono text-sm font-semibold">{endereco[field] || "-"}</p>
                          </div>
                        ))}
                      </div>
                      <div className="mt-3 flex items-center justify-between gap-2 text-xs text-muted-foreground">
                        <span>{endereco.area || "Area nao definida"}</span>
                        <Button size="sm" variant="outline" onClick={() => isProduto ? openTechDialog(item) : openEntityDialog("material", item)}>Editar</Button>
                      </div>
                    </div>
                  );
                })}
              </div>
              {!filtered.produtos.length && !filtered.materiais.length && <div className="rounded-lg border border-dashed p-8 text-center text-sm text-muted-foreground">Nenhum registro para enderecar.</div>}
            </CardContent>
          </Card>
          <ResponsiveTable
            rows={[...filtered.produtos.map((p) => ({ ...p, tipo_registro: "Produto acabado" })), ...filtered.materiais.map((m) => ({ ...m, tipo_registro: "Material" }))]}
            getKey={(r) => `${r.tipo_registro}-${r.id}`}
            emptyText="Nenhum endereco cadastrado."
            columns={[
              { key: "tipo_registro", label: "Tipo" },
              { key: "codigo_interno", label: "Codigo", render: (r) => <span className="font-mono">{r.codigo_interno || "-"}</span> },
              { key: "nome", label: "Item", render: (r) => r.nome_produto || r.nome },
              { key: "endereco", label: "Endereco", render: (r) => formatEndereco(r.enderecamento) },
              { key: "area", label: "Area", render: (r) => r.enderecamento?.area || "-" },
              { key: "acao", label: "Acao", render: (r) => <Button size="sm" variant="outline" onClick={() => r.tipo_registro === "Produto acabado" ? openTechDialog(r) : openEntityDialog("material", r)}>Editar</Button> },
            ]}
          />
        </TabsContent>

        <TabsContent value="categorias" className="space-y-4">
          <div className="flex flex-wrap justify-end gap-2">
            <Button variant="outline" onClick={() => openEntityDialog("categoriaProduto")} className="gap-2"><Plus className="h-4 w-4" /> Categoria Produto</Button>
            <Button onClick={() => openEntityDialog("categoriaMp")} className="gap-2"><Plus className="h-4 w-4" /> Categoria MP</Button>
          </div>
          <Card className="rounded-lg">
            <CardHeader><CardTitle className="text-base">Categorias de Produto</CardTitle></CardHeader>
            <CardContent>
              <ResponsiveTable
                rows={filtered.categoriasProduto}
                getKey={(r) => r.id || r.cat3}
                emptyText="Nenhuma categoria de produto."
                columns={[
                  { key: "cat3", label: "CAT3", render: (r) => <span className="font-mono">{r.cat3}</span> },
                  { key: "nome", label: "Nome" },
                  { key: "status", label: "Status", render: (r) => <StatusBadge value={r.status} /> },
                  { key: "acao", label: "Acao", render: (r) => (
                    <RowActions
                      onEdit={() => openEntityDialog("categoriaProduto", r)}
                      onDelete={() => inactivateEntity("categoriaProduto", r)}
                      extra={r.status === "pendente" ? <Button size="sm" variant="outline" onClick={() => approveCategoriaProduto(r.cat3)} className="gap-1"><CheckCircle2 className="h-3.5 w-3.5" /> Aprovar</Button> : null}
                    />
                  ) },
                ]}
              />
            </CardContent>
          </Card>
          <Card className="rounded-lg">
            <CardHeader><CardTitle className="text-base">Categorias de MPs e Insumos</CardTitle></CardHeader>
            <CardContent>
              <ResponsiveTable
                rows={filtered.categoriasMp}
                getKey={(r) => r.id}
                emptyText="Nenhuma categoria de MP."
                columns={[
                  { key: "catmp3", label: "CATMP3", render: (r) => <span className="font-mono">{r.catmp3}</span> },
                  { key: "nome", label: "Nome" },
                  { key: "tipo", label: "Tipo" },
                  { key: "status", label: "Status", render: (r) => <StatusBadge value={r.status} /> },
                  { key: "acao", label: "Acao", render: (r) => (
                    <RowActions
                      onEdit={() => openEntityDialog("categoriaMp", r)}
                      onDelete={() => inactivateEntity("categoriaMp", r)}
                      extra={r.status === "pendente" ? <Button size="sm" variant="outline" onClick={() => approveCategoriaMp(r.id)} className="gap-1"><CheckCircle2 className="h-3.5 w-3.5" /> Aprovar</Button> : null}
                    />
                  ) },
                ]}
              />
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="integracoes">
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {(dashboard?.integracoes || []).map((item) => (
              <Card key={item.nome} className="rounded-lg">
                <CardContent className="p-4">
                  <div className="mb-2 flex items-center justify-between">
                    <h3 className="font-semibold">{item.nome}</h3>
                    <StatusBadge value={item.status} />
                  </div>
                  <p className="text-sm text-muted-foreground">{item.detalhe}</p>
                </CardContent>
              </Card>
            ))}
          </div>
        </TabsContent>
      </Tabs>

      <CadastroDialog title={editing.kind === "cliente" ? "Editar cliente" : "Novo cliente"} open={dialog === "cliente"} onOpenChange={(v) => v ? setDialog("cliente") : closeDialog()} onSubmit={() => submit("cliente")} saving={saving}>
        <div className="rounded-lg border bg-muted/30 p-3 text-sm text-muted-foreground">
          Use este cadastro para incluir cliente novo ou trazer um cliente existente para a fonte unica. CNPJ e CLI4 sao validados contra duplicidade.
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Nome"><Input value={clienteForm.nome_empresa} onChange={(e) => setClienteForm({ ...clienteForm, nome_empresa: e.target.value })} /></Field>
          <Field label="CNPJ"><Input value={clienteForm.cnpj} onChange={(e) => setClienteForm({ ...clienteForm, cnpj: e.target.value })} /></Field>
          <Field label="CLI4"><Input value={clienteForm.cli4} onChange={(e) => setClienteForm({ ...clienteForm, cli4: e.target.value.toUpperCase() })} maxLength={4} /></Field>
          <Field label="Responsavel"><Input value={clienteForm.responsavel} onChange={(e) => setClienteForm({ ...clienteForm, responsavel: e.target.value })} /></Field>
          <Field label="Email"><Input value={clienteForm.email} onChange={(e) => setClienteForm({ ...clienteForm, email: e.target.value })} /></Field>
          <Field label="Telefone"><Input value={clienteForm.telefone} onChange={(e) => setClienteForm({ ...clienteForm, telefone: e.target.value })} /></Field>
          <Field label="Cidade"><Input value={clienteForm.cidade} onChange={(e) => setClienteForm({ ...clienteForm, cidade: e.target.value })} /></Field>
          <Field label="UF"><Input value={clienteForm.uf} onChange={(e) => setClienteForm({ ...clienteForm, uf: e.target.value.toUpperCase() })} maxLength={2} /></Field>
        </div>
        <Field label="Observacoes"><Textarea value={clienteForm.observacoes} onChange={(e) => setClienteForm({ ...clienteForm, observacoes: e.target.value })} /></Field>
      </CadastroDialog>

      <CadastroDialog title="Criar projeto direto" open={dialog === "projeto"} onOpenChange={(v) => v ? setDialog("projeto") : closeDialog()} onSubmit={() => submit("projeto")} saving={saving}>
        <div className="rounded-lg border bg-muted/30 p-3 text-sm text-muted-foreground">
          O projeto sera criado no CRM2 ja vinculado ao cliente selecionado e entrara em Projeto em Discussao.
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Cliente">
            <Select value={projetoForm.cliente_id} onValueChange={(v) => setProjetoForm({ ...projetoForm, cliente_id: v })}>
              <SelectTrigger><SelectValue placeholder="Selecione" /></SelectTrigger>
              <SelectContent>{clientes.map((c) => <SelectItem key={c.id} value={c.id}>{c.nome_empresa} ({c.cli4 || "sem CLI4"})</SelectItem>)}</SelectContent>
            </Select>
          </Field>
          <Field label="Nome do projeto"><Input value={projetoForm.nome_projeto} onChange={(e) => setProjetoForm({ ...projetoForm, nome_projeto: e.target.value })} /></Field>
          <Field label="Categoria">
            <Select value={projetoForm.categoria} onValueChange={(v) => setProjetoForm({ ...projetoForm, categoria: v })}>
              <SelectTrigger><SelectValue placeholder="Opcional" /></SelectTrigger>
              <SelectContent>{activeCategoriasProduto.map((c) => <SelectItem key={c.cat3} value={c.nome || c.cat3}>{c.cat3} - {c.nome}</SelectItem>)}</SelectContent>
            </Select>
          </Field>
          <Field label="Prazo da amostra"><Input type="date" value={projetoForm.prazo_desejado_amostra} onChange={(e) => setProjetoForm({ ...projetoForm, prazo_desejado_amostra: e.target.value })} /></Field>
        </div>
        <Field label="Briefing resumido"><Textarea value={projetoForm.briefing_resumido} onChange={(e) => setProjetoForm({ ...projetoForm, briefing_resumido: e.target.value })} /></Field>
        <Field label="Observacoes"><Textarea value={projetoForm.observacoes_livres} onChange={(e) => setProjetoForm({ ...projetoForm, observacoes_livres: e.target.value })} /></Field>
      </CadastroDialog>

      <CadastroDialog title={editing.kind === "fornecedor" ? "Editar fornecedor" : "Novo fornecedor"} open={dialog === "fornecedor"} onOpenChange={(v) => v ? setDialog("fornecedor") : closeDialog()} onSubmit={() => submit("fornecedor")} saving={saving}>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Razao social"><Input value={fornecedorForm.razao_social} onChange={(e) => setFornecedorForm({ ...fornecedorForm, razao_social: e.target.value })} /></Field>
          <Field label="CNPJ"><Input value={fornecedorForm.cnpj} onChange={(e) => setFornecedorForm({ ...fornecedorForm, cnpj: e.target.value })} /></Field>
          <Field label="Nome fantasia"><Input value={fornecedorForm.nome_fantasia} onChange={(e) => setFornecedorForm({ ...fornecedorForm, nome_fantasia: e.target.value })} /></Field>
          <Field label="Categoria"><Input value={fornecedorForm.categoria} onChange={(e) => setFornecedorForm({ ...fornecedorForm, categoria: e.target.value })} /></Field>
          <Field label="Email"><Input value={fornecedorForm.email} onChange={(e) => setFornecedorForm({ ...fornecedorForm, email: e.target.value })} /></Field>
          <Field label="Telefone"><Input value={fornecedorForm.telefone} onChange={(e) => setFornecedorForm({ ...fornecedorForm, telefone: e.target.value })} /></Field>
        </div>
        <Field label="Observacoes"><Textarea value={fornecedorForm.observacoes} onChange={(e) => setFornecedorForm({ ...fornecedorForm, observacoes: e.target.value })} /></Field>
      </CadastroDialog>

      <CadastroDialog title={editing.kind === "categoriaProduto" ? "Editar categoria de produto" : "Nova categoria de produto"} open={dialog === "categoriaProduto"} onOpenChange={(v) => v ? setDialog("categoriaProduto") : closeDialog()} onSubmit={() => submit("categoriaProduto")} saving={saving}>
        <div className="grid gap-3 sm:grid-cols-3">
          <Field label="CAT3"><Input value={categoriaProdutoForm.cat3} onChange={(e) => setCategoriaProdutoForm({ ...categoriaProdutoForm, cat3: e.target.value.toUpperCase() })} maxLength={3} disabled={editing.kind === "categoriaProduto"} /></Field>
          <Field label="Nome"><Input value={categoriaProdutoForm.nome} onChange={(e) => setCategoriaProdutoForm({ ...categoriaProdutoForm, nome: e.target.value })} /></Field>
          <Field label="Status">
            <Select value={categoriaProdutoForm.status} onValueChange={(v) => setCategoriaProdutoForm({ ...categoriaProdutoForm, status: v })} disabled={editing.kind !== "categoriaProduto"}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="pendente">Pendente</SelectItem>
                <SelectItem value="ativa">Ativa</SelectItem>
                <SelectItem value="inativa">Inativa</SelectItem>
              </SelectContent>
            </Select>
          </Field>
        </div>
        <Field label="Justificativa"><Textarea value={categoriaProdutoForm.justificativa} onChange={(e) => setCategoriaProdutoForm({ ...categoriaProdutoForm, justificativa: e.target.value })} /></Field>
      </CadastroDialog>

      <CadastroDialog title={editing.kind === "categoriaMp" ? "Editar categoria de MP/Insumo" : "Nova categoria de MP/Insumo"} open={dialog === "categoriaMp"} onOpenChange={(v) => v ? setDialog("categoriaMp") : closeDialog()} onSubmit={() => submit("categoriaMp")} saving={saving}>
        <div className="grid gap-3 sm:grid-cols-3">
          <Field label="CATMP3"><Input value={categoriaMpForm.catmp3} onChange={(e) => setCategoriaMpForm({ ...categoriaMpForm, catmp3: e.target.value.toUpperCase() })} maxLength={3} disabled={editing.kind === "categoriaMp"} /></Field>
          <Field label="Nome"><Input value={categoriaMpForm.nome} onChange={(e) => setCategoriaMpForm({ ...categoriaMpForm, nome: e.target.value })} /></Field>
          <Field label="Tipo">
            <Select value={categoriaMpForm.tipo} onValueChange={(v) => setCategoriaMpForm({ ...categoriaMpForm, tipo: v })}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="mp">MP</SelectItem>
                <SelectItem value="insumo">Insumo</SelectItem>
                <SelectItem value="embalagem">Embalagem</SelectItem>
              </SelectContent>
            </Select>
          </Field>
        </div>
        <Field label="Descricao"><Textarea value={categoriaMpForm.descricao} onChange={(e) => setCategoriaMpForm({ ...categoriaMpForm, descricao: e.target.value })} /></Field>
        <Field label="Justificativa"><Textarea value={categoriaMpForm.justificativa} onChange={(e) => setCategoriaMpForm({ ...categoriaMpForm, justificativa: e.target.value })} /></Field>
      </CadastroDialog>

      <CadastroDialog title={editing.kind === "produto" ? "Editar produto final" : "Novo produto final"} open={dialog === "produto"} onOpenChange={(v) => v ? setDialog("produto") : closeDialog()} onSubmit={() => submit("produto")} saving={saving}>
        <div className="rounded-lg border bg-muted/30 p-3 text-sm text-muted-foreground">
          SKU gerado automaticamente como CAT3-CLI4-SEQ4. O CLI4 do cliente sera congelado apos a criacao.
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Produto"><Input value={produtoForm.nome_produto} onChange={(e) => setProdutoForm({ ...produtoForm, nome_produto: e.target.value })} /></Field>
          <Field label="Cliente">
            <Select value={produtoForm.cliente_id} onValueChange={(v) => setProdutoForm({ ...produtoForm, cliente_id: v })} disabled={editing.kind === "produto"}>
              <SelectTrigger><SelectValue placeholder="Selecione" /></SelectTrigger>
              <SelectContent>{clientes.map((c) => <SelectItem key={c.id} value={c.id}>{c.nome_empresa} ({c.cli4 || "sem CLI4"})</SelectItem>)}</SelectContent>
            </Select>
          </Field>
          <Field label="Categoria Produto">
            <Select value={produtoForm.cat3} onValueChange={(v) => setProdutoForm({ ...produtoForm, cat3: v })} disabled={editing.kind === "produto"}>
              <SelectTrigger><SelectValue placeholder="CAT3" /></SelectTrigger>
              <SelectContent>{activeCategoriasProduto.map((c) => <SelectItem key={c.cat3} value={c.cat3}>{c.cat3} - {c.nome}</SelectItem>)}</SelectContent>
            </Select>
          </Field>
          <Field label="Volume"><Input type="number" value={produtoForm.volume} onChange={(e) => setProdutoForm({ ...produtoForm, volume: e.target.value })} /></Field>
          <Field label="Unidade"><Input value={produtoForm.unidade_volume} onChange={(e) => setProdutoForm({ ...produtoForm, unidade_volume: e.target.value })} /></Field>
          <Field label="P&D concluido"><Input value={produtoForm.pd_request_id} onChange={(e) => setProdutoForm({ ...produtoForm, pd_request_id: e.target.value })} placeholder="ID do P&D aprovado, se houver" /></Field>
        </div>
        <Field label="Observacoes"><Textarea value={produtoForm.observacoes} onChange={(e) => setProdutoForm({ ...produtoForm, observacoes: e.target.value })} /></Field>
      </CadastroDialog>

      <CadastroDialog title={editing.kind === "material" ? "Editar MP/Insumo" : "Novo MP/Insumo"} open={dialog === "material"} onOpenChange={(v) => v ? setDialog("material") : closeDialog()} onSubmit={() => submit("material")} saving={saving}>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Tipo">
            <Select value={materialForm.tipo} onValueChange={(v) => setMaterialForm({ ...materialForm, tipo: v })}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="mp">Materia-prima</SelectItem>
                <SelectItem value="insumo">Insumo</SelectItem>
                <SelectItem value="EP">Embalagem primaria</SelectItem>
                <SelectItem value="ES">Embalagem secundaria</SelectItem>
                <SelectItem value="RT">Rotulo/Etiqueta</SelectItem>
              </SelectContent>
            </Select>
          </Field>
          <Field label="Nome"><Input value={materialForm.nome} onChange={(e) => setMaterialForm({ ...materialForm, nome: e.target.value })} /></Field>
          <Field label="Categoria MP/Insumo">
            <Select value={materialForm.categoria_mp_id} onValueChange={(v) => setMaterialForm({ ...materialForm, categoria_mp_id: v })}>
              <SelectTrigger><SelectValue placeholder="Opcional" /></SelectTrigger>
              <SelectContent>{activeCategoriasMp.map((c) => <SelectItem key={c.id} value={c.id}>{c.catmp3} - {c.nome}</SelectItem>)}</SelectContent>
            </Select>
          </Field>
          <Field label="Subtipo"><Input value={materialForm.subtipo} onChange={(e) => setMaterialForm({ ...materialForm, subtipo: e.target.value })} /></Field>
          <Field label="Unidade estoque"><Input value={materialForm.unidade_estoque} onChange={(e) => setMaterialForm({ ...materialForm, unidade_estoque: e.target.value })} /></Field>
          <Field label="Unidade compra"><Input value={materialForm.unidade_compra} onChange={(e) => setMaterialForm({ ...materialForm, unidade_compra: e.target.value })} /></Field>
          <Field label="Fornecedor">
            <Select value={materialForm.fornecedor_id} onValueChange={(v) => setMaterialForm({ ...materialForm, fornecedor_id: v })}>
              <SelectTrigger><SelectValue placeholder="Opcional" /></SelectTrigger>
              <SelectContent>{fornecedores.map((f) => <SelectItem key={f.id} value={f.id}>{f.razao_social}</SelectItem>)}</SelectContent>
            </Select>
          </Field>
          <Field label="Fator conversao"><Input type="number" value={materialForm.fator_conversao} onChange={(e) => setMaterialForm({ ...materialForm, fator_conversao: Number(e.target.value) || 1 })} /></Field>
        </div>
        <Separator />
        <div className="grid gap-3 sm:grid-cols-4">
          <Field label="Rua"><Input value={materialForm.enderecamento?.rua || ""} onChange={(e) => setMaterialForm({ ...materialForm, enderecamento: { ...(materialForm.enderecamento || emptyEndereco), rua: e.target.value } })} /></Field>
          <Field label="Modulo"><Input value={materialForm.enderecamento?.modulo || ""} onChange={(e) => setMaterialForm({ ...materialForm, enderecamento: { ...(materialForm.enderecamento || emptyEndereco), modulo: e.target.value } })} /></Field>
          <Field label="Nivel"><Input value={materialForm.enderecamento?.nivel || ""} onChange={(e) => setMaterialForm({ ...materialForm, enderecamento: { ...(materialForm.enderecamento || emptyEndereco), nivel: e.target.value } })} /></Field>
          <Field label="Posicao"><Input value={materialForm.enderecamento?.posicao || ""} onChange={(e) => setMaterialForm({ ...materialForm, enderecamento: { ...(materialForm.enderecamento || emptyEndereco), posicao: e.target.value } })} /></Field>
          <Field label="Area"><Input value={materialForm.enderecamento?.area || ""} onChange={(e) => setMaterialForm({ ...materialForm, enderecamento: { ...(materialForm.enderecamento || emptyEndereco), area: e.target.value } })} /></Field>
          <Field label="Temperatura"><Input value={materialForm.enderecamento?.temperatura || ""} onChange={(e) => setMaterialForm({ ...materialForm, enderecamento: { ...(materialForm.enderecamento || emptyEndereco), temperatura: e.target.value } })} /></Field>
          <Field label="Capacidade paletes"><Input type="number" value={materialForm.enderecamento?.capacidade_paletes || ""} onChange={(e) => setMaterialForm({ ...materialForm, enderecamento: { ...(materialForm.enderecamento || emptyEndereco), capacidade_paletes: e.target.value } })} /></Field>
          <Field label="Status">
            <Select value={materialForm.status || "ativo"} onValueChange={(v) => setMaterialForm({ ...materialForm, status: v })}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="ativo">Ativo</SelectItem>
                <SelectItem value="inativo">Inativo</SelectItem>
                <SelectItem value="homologado">Homologado</SelectItem>
                <SelectItem value="pendente">Pendente</SelectItem>
              </SelectContent>
            </Select>
          </Field>
        </div>
        <Field label="Observacoes"><Textarea value={materialForm.observacoes} onChange={(e) => setMaterialForm({ ...materialForm, observacoes: e.target.value })} /></Field>
      </CadastroDialog>

      <CadastroDialog title={`Engenharia tecnica - ${productTechForm.produto_nome || "produto"}`} open={dialog === "produtoTecnico"} onOpenChange={(v) => v ? setDialog("produtoTecnico") : closeDialog()} onSubmit={() => submit("produtoTecnico")} saving={saving}>
        <div className="rounded-lg border bg-muted/30 p-3 text-sm text-muted-foreground">
          Cadastre formula do granel, BOM de embalagem, especificacoes tecnicas e endereco mestre do SKU. Estes dados alimentam ficha tecnica, MRP, PCP e WMS.
        </div>

        <div className="space-y-3">
          <div className="flex items-center justify-between gap-3">
            <h3 className="text-sm font-semibold">Formula completa por produto</h3>
            <Button type="button" size="sm" variant="outline" onClick={() => setProductTechForm({ ...productTechForm, formula: [...productTechForm.formula, { material_id: "", material_nome: "", fase: "A", percentual: "", funcao: "" }] })}>
              + Linha
            </Button>
          </div>
          <div className="grid gap-2">
            {productTechForm.formula.map((item, index) => (
              <div key={`formula-${index}`} className="grid gap-2 rounded-lg border p-3 md:grid-cols-[1.3fr_0.7fr_0.7fr_1fr_auto]">
                <Field label="Materia-prima / ativo">
                  <Select value={item.material_id || "manual"} onValueChange={(v) => {
                    const material = materiais.find((m) => m.id === v);
                    const next = [...productTechForm.formula];
                    next[index] = { ...item, material_id: v === "manual" ? "" : v, material_nome: material?.nome || item.material_nome };
                    setProductTechForm({ ...productTechForm, formula: next });
                  }}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="manual">Digitar manualmente</SelectItem>
                      {materiais.map((m) => <SelectItem key={m.id} value={m.id}>{m.codigo_interno} - {m.nome}</SelectItem>)}
                    </SelectContent>
                  </Select>
                </Field>
                <Field label="Nome manual"><Input value={item.material_nome || ""} onChange={(e) => {
                  const next = [...productTechForm.formula];
                  next[index] = { ...item, material_nome: e.target.value };
                  setProductTechForm({ ...productTechForm, formula: next });
                }} /></Field>
                <Field label="%"><Input type="number" value={item.percentual ?? ""} onChange={(e) => {
                  const next = [...productTechForm.formula];
                  next[index] = { ...item, percentual: e.target.value };
                  setProductTechForm({ ...productTechForm, formula: next });
                }} /></Field>
                <Field label="Funcao"><Input value={item.funcao || ""} placeholder="Base, ativo, fragrancia..." onChange={(e) => {
                  const next = [...productTechForm.formula];
                  next[index] = { ...item, funcao: e.target.value };
                  setProductTechForm({ ...productTechForm, formula: next });
                }} /></Field>
                <Button type="button" size="sm" variant="ghost" className="self-end text-destructive" onClick={() => setProductTechForm({ ...productTechForm, formula: productTechForm.formula.filter((_, i) => i !== index) || [] })}>
                  <Trash2 className="h-4 w-4" />
                </Button>
              </div>
            ))}
          </div>
        </div>

        <Separator />

        <div className="space-y-3">
          <div className="flex items-center justify-between gap-3">
            <h3 className="text-sm font-semibold">BOM detalhado por SKU/produto</h3>
            <Button type="button" size="sm" variant="outline" onClick={() => setProductTechForm({ ...productTechForm, bom: [...productTechForm.bom, { material_id: "", material_nome: "", quantidade: "", unidade: "un", etapa: "" }] })}>
              + Linha
            </Button>
          </div>
          <div className="grid gap-2">
            {productTechForm.bom.map((item, index) => (
              <div key={`bom-${index}`} className="grid gap-2 rounded-lg border p-3 md:grid-cols-[1.3fr_0.7fr_0.7fr_1fr_auto]">
                <Field label="Insumo / embalagem">
                  <Select value={item.material_id || "manual"} onValueChange={(v) => {
                    const material = materiais.find((m) => m.id === v);
                    const next = [...productTechForm.bom];
                    next[index] = { ...item, material_id: v === "manual" ? "" : v, material_nome: material?.nome || item.material_nome, unidade: material?.unidade_estoque || item.unidade };
                    setProductTechForm({ ...productTechForm, bom: next });
                  }}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="manual">Digitar manualmente</SelectItem>
                      {materiais.map((m) => <SelectItem key={m.id} value={m.id}>{m.codigo_interno} - {m.nome}</SelectItem>)}
                    </SelectContent>
                  </Select>
                </Field>
                <Field label="Quantidade"><Input type="number" value={item.quantidade ?? ""} onChange={(e) => {
                  const next = [...productTechForm.bom];
                  next[index] = { ...item, quantidade: e.target.value };
                  setProductTechForm({ ...productTechForm, bom: next });
                }} /></Field>
                <Field label="Unidade"><Input value={item.unidade || ""} onChange={(e) => {
                  const next = [...productTechForm.bom];
                  next[index] = { ...item, unidade: e.target.value };
                  setProductTechForm({ ...productTechForm, bom: next });
                }} /></Field>
                <Field label="Etapa"><Input value={item.etapa || ""} placeholder="Envase, rotulagem..." onChange={(e) => {
                  const next = [...productTechForm.bom];
                  next[index] = { ...item, etapa: e.target.value };
                  setProductTechForm({ ...productTechForm, bom: next });
                }} /></Field>
                <Button type="button" size="sm" variant="ghost" className="self-end text-destructive" onClick={() => setProductTechForm({ ...productTechForm, bom: productTechForm.bom.filter((_, i) => i !== index) || [] })}>
                  <Trash2 className="h-4 w-4" />
                </Button>
              </div>
            ))}
          </div>
        </div>

        <Separator />

        <div className="space-y-3">
          <h3 className="text-sm font-semibold">Especificacoes tecnicas completas</h3>
          <div className="grid gap-3 sm:grid-cols-2">
            {Object.entries(productTechForm.especificacoes_tecnicas).map(([key, value]) => (
              <Field key={key} label={key.replaceAll("_", " ")}>
                <Input value={value || ""} onChange={(e) => setProductTechForm({
                  ...productTechForm,
                  especificacoes_tecnicas: { ...productTechForm.especificacoes_tecnicas, [key]: e.target.value },
                })} />
              </Field>
            ))}
          </div>
        </div>

        <Separator />

        <div className="space-y-3">
          <h3 className="text-sm font-semibold">Endereco / estrutura de armazenagem</h3>
          <div className="grid gap-3 sm:grid-cols-4">
            {Object.entries(productTechForm.enderecamento).map(([key, value]) => (
              <Field key={key} label={key.replaceAll("_", " ")}>
                <Input value={value || ""} onChange={(e) => setProductTechForm({
                  ...productTechForm,
                  enderecamento: { ...productTechForm.enderecamento, [key]: e.target.value },
                })} />
              </Field>
            ))}
          </div>
        </div>
      </CadastroDialog>
    </div>
  );
}
