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
  Database,
  Factory,
  Layers3,
  Package,
  Plus,
  RefreshCw,
  Search,
  ShieldCheck,
  Tags,
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
                  <span className="max-w-[65%] text-right text-sm font-medium">{c.render ? c.render(row) : row[c.key]}</span>
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
  const [categoriaMpForm, setCategoriaMpForm] = useState(emptyCategoriaMp);
  const [produtoForm, setProdutoForm] = useState(emptyProduto);
  const [materialForm, setMaterialForm] = useState(emptyMaterial);
  const [projetoForm, setProjetoForm] = useState(emptyProjeto);

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

  const submit = async (kind) => {
    setSaving(true);
    try {
      if (kind === "cliente") {
        await api.post("/cadastros/clientes", clienteForm);
        setClienteForm(emptyCliente);
      }
      if (kind === "fornecedor") {
        await api.post("/cadastros/fornecedores", fornecedorForm);
        setFornecedorForm(emptyFornecedor);
      }
      if (kind === "categoriaMp") {
        await api.post("/cadastros/categorias-mp", categoriaMpForm);
        setCategoriaMpForm(emptyCategoriaMp);
      }
      if (kind === "produto") {
        await api.post("/cadastros/produtos", {
          ...produtoForm,
          volume: produtoForm.volume === "" ? null : Number(produtoForm.volume),
        });
        setProdutoForm(emptyProduto);
      }
      if (kind === "material") {
        await api.post("/cadastros/materiais-cadastro", materialForm);
        setMaterialForm(emptyMaterial);
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
      setDialog(null);
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
          <Button onClick={() => setDialog("cliente")} className="gap-2"><Plus className="h-4 w-4" /> Cliente</Button>
          <Button variant="outline" onClick={() => setDialog("projeto")} className="gap-2"><FolderPlus className="h-4 w-4" /> Projeto</Button>
          <Button variant="outline" onClick={() => setDialog("fornecedor")} className="gap-2"><Plus className="h-4 w-4" /> Fornecedor</Button>
          <Button variant="outline" onClick={() => setDialog("produto")} className="gap-2"><Plus className="h-4 w-4" /> Produto</Button>
          <Button variant="outline" onClick={() => setDialog("material")} className="gap-2"><Plus className="h-4 w-4" /> Material</Button>
        </div>
      </div>

      <SearchBar value={search} onChange={setSearch} onRefresh={loadAll} placeholder="Buscar por SKU, cliente, fornecedor, CNPJ ou categoria..." />

      <Tabs value={tab} onValueChange={setTab} className="w-full">
        <TabsList className="grid h-auto grid-cols-2 gap-1 sm:grid-cols-3 lg:grid-cols-7">
          <TabsTrigger value="dashboard">Visao</TabsTrigger>
          <TabsTrigger value="clientes">Clientes</TabsTrigger>
          <TabsTrigger value="fornecedores">Fornecedores</TabsTrigger>
          <TabsTrigger value="produtos">Produtos</TabsTrigger>
          <TabsTrigger value="materiais">MPs/Insumos</TabsTrigger>
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
              { key: "acao", label: "Acao", render: (r) => <Button size="sm" variant="outline" onClick={() => openProjetoDialog(r)} className="gap-1"><FolderPlus className="h-3.5 w-3.5" /> Projeto</Button> },
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
            ]}
          />
        </TabsContent>

        <TabsContent value="categorias" className="space-y-4">
          <div className="flex justify-end">
            <Button onClick={() => setDialog("categoriaMp")} className="gap-2"><Plus className="h-4 w-4" /> Categoria MP</Button>
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
                  { key: "acao", label: "Acao", render: (r) => r.status === "pendente" ? <Button size="sm" variant="outline" onClick={() => approveCategoriaMp(r.id)} className="gap-1"><CheckCircle2 className="h-3.5 w-3.5" /> Aprovar</Button> : "-" },
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

      <CadastroDialog title="Novo cliente" open={dialog === "cliente"} onOpenChange={(v) => setDialog(v ? "cliente" : null)} onSubmit={() => submit("cliente")} saving={saving}>
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

      <CadastroDialog title="Criar projeto direto" open={dialog === "projeto"} onOpenChange={(v) => setDialog(v ? "projeto" : null)} onSubmit={() => submit("projeto")} saving={saving}>
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

      <CadastroDialog title="Novo fornecedor" open={dialog === "fornecedor"} onOpenChange={(v) => setDialog(v ? "fornecedor" : null)} onSubmit={() => submit("fornecedor")} saving={saving}>
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

      <CadastroDialog title="Nova categoria de MP/Insumo" open={dialog === "categoriaMp"} onOpenChange={(v) => setDialog(v ? "categoriaMp" : null)} onSubmit={() => submit("categoriaMp")} saving={saving}>
        <div className="grid gap-3 sm:grid-cols-3">
          <Field label="CATMP3"><Input value={categoriaMpForm.catmp3} onChange={(e) => setCategoriaMpForm({ ...categoriaMpForm, catmp3: e.target.value.toUpperCase() })} maxLength={3} /></Field>
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

      <CadastroDialog title="Novo produto final" open={dialog === "produto"} onOpenChange={(v) => setDialog(v ? "produto" : null)} onSubmit={() => submit("produto")} saving={saving}>
        <div className="rounded-lg border bg-muted/30 p-3 text-sm text-muted-foreground">
          SKU gerado automaticamente como CAT3-CLI4-SEQ4. O CLI4 do cliente sera congelado apos a criacao.
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Produto"><Input value={produtoForm.nome_produto} onChange={(e) => setProdutoForm({ ...produtoForm, nome_produto: e.target.value })} /></Field>
          <Field label="Cliente">
            <Select value={produtoForm.cliente_id} onValueChange={(v) => setProdutoForm({ ...produtoForm, cliente_id: v })}>
              <SelectTrigger><SelectValue placeholder="Selecione" /></SelectTrigger>
              <SelectContent>{clientes.map((c) => <SelectItem key={c.id} value={c.id}>{c.nome_empresa} ({c.cli4 || "sem CLI4"})</SelectItem>)}</SelectContent>
            </Select>
          </Field>
          <Field label="Categoria Produto">
            <Select value={produtoForm.cat3} onValueChange={(v) => setProdutoForm({ ...produtoForm, cat3: v })}>
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

      <CadastroDialog title="Novo MP/Insumo" open={dialog === "material"} onOpenChange={(v) => setDialog(v ? "material" : null)} onSubmit={() => submit("material")} saving={saving}>
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
        <Field label="Observacoes"><Textarea value={materialForm.observacoes} onChange={(e) => setMaterialForm({ ...materialForm, observacoes: e.target.value })} /></Field>
      </CadastroDialog>
    </div>
  );
}
