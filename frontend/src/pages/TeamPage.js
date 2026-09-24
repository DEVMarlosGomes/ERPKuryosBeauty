import { useState, useEffect, useCallback } from "react";
import api from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from "@/components/ui/alert-dialog";
import { Separator } from "@/components/ui/separator";
import { toast } from "sonner";
import { UserPlus, Pencil, Trash2, Copy, KeyRound, Shield, Users, Plus, ToggleLeft, ToggleRight } from "lucide-react";

const ROLES = [
    { value: "admin",               label: "Admin",              color: "bg-violet-100 text-violet-800 dark:bg-violet-900/40 dark:text-violet-300" },
    { value: "lider_pd",            label: "Líder P&D",          color: "bg-indigo-100 text-indigo-800 dark:bg-indigo-900/40 dark:text-indigo-300" },
    { value: "formulador",          label: "Formulador",         color: "bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-300" },
    { value: "engenharia_produto",  label: "Eng. Produto",       color: "bg-cyan-100 text-cyan-800 dark:bg-cyan-900/40 dark:text-cyan-300" },
    { value: "qa",                  label: "Qualidade (QA)",     color: "bg-teal-100 text-teal-800 dark:bg-teal-900/40 dark:text-teal-300" },
    { value: "compras",             label: "Compras",            color: "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300" },
    { value: "logistica",           label: "Logística",          color: "bg-sky-100 text-sky-800 dark:bg-sky-900/40 dark:text-sky-300" },
    { value: "estoque",             label: "Estoque / WMS",      color: "bg-stone-100 text-stone-800 dark:bg-stone-900/40 dark:text-stone-300" },
    { value: "pcp",                 label: "PCP",                color: "bg-purple-100 text-purple-800 dark:bg-purple-900/40 dark:text-purple-300" },
    { value: "producao",            label: "Produção",           color: "bg-fuchsia-100 text-fuchsia-800 dark:bg-fuchsia-900/40 dark:text-fuchsia-300" },
    { value: "faturamento",         label: "Faturamento",        color: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300" },
    { value: "vendedor",            label: "Vendedor",           color: "bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-300" },
    { value: "sales_ops",           label: "Sales Ops",          color: "bg-lime-100 text-lime-800 dark:bg-lime-900/40 dark:text-lime-300" },
    { value: "sucesso_cliente",     label: "Sucesso do Cliente", color: "bg-orange-100 text-orange-800 dark:bg-orange-900/40 dark:text-orange-300" },
    { value: "gestor",              label: "Gestor",             color: "bg-rose-100 text-rose-800 dark:bg-rose-900/40 dark:text-rose-300" },
];

const roleByValue = Object.fromEntries(ROLES.map(r => [r.value, r]));

function RoleBadge({ role }) {
    const r = roleByValue[role] || { label: role, color: "bg-muted text-muted-foreground" };
    return (
        <Badge className={`${r.color} border-0 text-xs font-medium gap-1 whitespace-nowrap`}>
            <Shield className="h-3 w-3" />
            {r.label}
        </Badge>
    );
}

function UserAvatar({ name, size = 40 }) {
    const initials = (name || "?").split(" ").slice(0, 2).map(w => w[0]).join("").toUpperCase();
    const colors = ["bg-violet-500", "bg-blue-500", "bg-teal-500", "bg-amber-500", "bg-rose-500", "bg-indigo-500"];
    const color = colors[(name?.charCodeAt(0) || 0) % colors.length];
    return (
        <div className={`${color} rounded-full flex items-center justify-center text-white font-semibold flex-shrink-0`}
            style={{ width: size, height: size, fontSize: size * 0.38 }}>
            {initials}
        </div>
    );
}

export default function TeamPage() {
    const { user } = useAuth();
    const [users, setUsers] = useState([]);
    const [loading, setLoading] = useState(true);
    const [leadSources, setLeadSources] = useState([]);
    const [lsLoading, setLsLoading] = useState(false);

    // Modals
    const [inviteOpen, setInviteOpen] = useState(false);
    const [inviteForm, setInviteForm] = useState({ email: "", name: "", role: "vendedor" });
    const [inviteResult, setInviteResult] = useState(null);
    const [inviteSubmitting, setInviteSubmitting] = useState(false);

    const [editOpen, setEditOpen] = useState(false);
    const [editTarget, setEditTarget] = useState(null);
    const [editForm, setEditForm] = useState({ name: "", new_password: "", role: "" });
    const [editSubmitting, setEditSubmitting] = useState(false);

    const [deleteTarget, setDeleteTarget] = useState(null);

    // Lead sources
    const [showAddSource, setShowAddSource] = useState(false);
    const [addSourceForm, setAddSourceForm] = useState({ nome: "", valor: "", grupo: "" });
    const [editingSource, setEditingSource] = useState(null);
    const [editSourceForm, setEditSourceForm] = useState({ nome: "", grupo: "" });

    const isAdmin = user?.role === "admin";

    const loadUsers = useCallback(async () => {
        try {
            const { data } = await api.get("/users");
            setUsers(data);
        } catch { toast.error("Erro ao carregar usuários"); }
        finally { setLoading(false); }
    }, []);

    const loadLeadSources = useCallback(async () => {
        setLsLoading(true);
        try {
            const { data } = await api.get("/crm/config/lead-sources");
            setLeadSources(data);
        } catch {}
        finally { setLsLoading(false); }
    }, []);

    useEffect(() => { loadUsers(); loadLeadSources(); }, [loadUsers, loadLeadSources]);

    const handleInvite = async () => {
        if (!inviteForm.email || !inviteForm.name) return;
        setInviteSubmitting(true);
        try {
            const { data } = await api.post("/users/invite", inviteForm);
            setInviteResult(data);
            toast.success(`${data.name} convidado com sucesso`);
            loadUsers();
        } catch (e) {
            toast.error(e.response?.data?.detail || "Erro ao convidar");
        } finally { setInviteSubmitting(false); }
    };

    const openEdit = (u) => {
        setEditTarget(u);
        setEditForm({ name: u.name, new_password: "", role: u.role });
        setEditOpen(true);
    };

    const handleEdit = async () => {
        if (!editTarget) return;
        setEditSubmitting(true);
        try {
            const updates = [];
            const patch = {};
            if (editForm.name !== editTarget.name) patch.name = editForm.name;
            if (editForm.new_password) patch.new_password = editForm.new_password;

            if (Object.keys(patch).length > 0) {
                await api.patch(`/users/${editTarget.id}`, patch);
                updates.push("dados");
            }
            if (editForm.role !== editTarget.role) {
                await api.put(`/users/${editTarget.id}/role`, { role: editForm.role });
                updates.push("role");
            }
            if (updates.length === 0) { setEditOpen(false); return; }
            toast.success("Usuário atualizado");
            setEditOpen(false);
            loadUsers();
        } catch (e) {
            toast.error(e.response?.data?.detail || "Erro ao atualizar");
        } finally { setEditSubmitting(false); }
    };

    const handleDelete = async () => {
        if (!deleteTarget) return;
        try {
            await api.delete(`/users/${deleteTarget.id}`);
            toast.success(`${deleteTarget.name} removido`);
            setDeleteTarget(null);
            loadUsers();
        } catch (e) {
            toast.error(e.response?.data?.detail || "Erro ao remover");
        }
    };

    const createLeadSource = async () => {
        if (!addSourceForm.nome || !addSourceForm.valor) return;
        try {
            await api.post("/crm/config/lead-sources", addSourceForm);
            toast.success("Canal criado");
            setShowAddSource(false);
            setAddSourceForm({ nome: "", valor: "", grupo: "" });
            loadLeadSources();
        } catch (e) { toast.error(e.response?.data?.detail || "Erro ao criar"); }
    };

    const updateLeadSource = async (id, patch) => {
        try {
            await api.patch(`/crm/config/lead-sources/${id}`, patch);
            toast.success("Canal atualizado");
            setEditingSource(null);
            loadLeadSources();
        } catch (e) { toast.error(e.response?.data?.detail || "Erro"); }
    };

    const toggleLeadSource = async (src) => {
        try {
            await api.patch(`/crm/config/lead-sources/${src.id}`, { ativo: !src.ativo });
            loadLeadSources();
        } catch { toast.error("Erro"); }
    };

    if (loading) return (
        <div className="p-6 sm:p-8 space-y-4 page-enter" data-testid="team-loading">
            {[1,2,3,4].map(i => (
                <div key={i} className="h-16 rounded-xl bg-muted animate-pulse" />
            ))}
        </div>
    );

    return (
        <div className="p-6 sm:p-8 page-enter max-w-4xl mx-auto" data-testid="team-page">

            {/* Header */}
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-8">
                <div>
                    <h1 className="text-2xl sm:text-3xl font-heading font-semibold tracking-tight flex items-center gap-2">
                        <Users className="h-7 w-7 text-muted-foreground" />
                        Equipe
                    </h1>
                    <p className="text-sm text-muted-foreground mt-1">
                        {users.length} {users.length === 1 ? "membro" : "membros"} · {ROLES.length} perfis disponíveis
                    </p>
                </div>
                {isAdmin && (
                    <Button onClick={() => { setInviteOpen(true); setInviteResult(null); setInviteForm({ email: "", name: "", role: "vendedor" }); }}
                        className="gap-2 shrink-0" data-testid="invite-btn">
                        <UserPlus className="h-4 w-4" />
                        Novo Usuário
                    </Button>
                )}
            </div>

            {/* Users table */}
            <div className="rounded-xl border border-border overflow-hidden mb-10">
                {/* Table header */}
                <div className="hidden sm:grid grid-cols-[1fr_1fr_auto_auto] gap-4 px-4 py-2.5 bg-muted/50 text-xs font-medium text-muted-foreground uppercase tracking-wider">
                    <span>Usuário</span>
                    <span>Email</span>
                    <span>Perfil</span>
                    {isAdmin && <span />}
                </div>

                <div className="divide-y divide-border">
                    {users.map((u) => (
                        <div key={u.id}
                            className="flex flex-col sm:grid sm:grid-cols-[1fr_1fr_auto_auto] sm:items-center gap-3 sm:gap-4 p-4 hover:bg-muted/30 transition-colors"
                            data-testid={`user-${u.id}`}>

                            {/* Name + avatar */}
                            <div className="flex items-center gap-3">
                                <UserAvatar name={u.name} />
                                <div className="min-w-0">
                                    <p className="font-medium text-sm truncate">
                                        {u.name}
                                        {u.id === user?.id && (
                                            <span className="ml-2 text-[10px] bg-primary/10 text-primary px-1.5 py-0.5 rounded-full font-medium">você</span>
                                        )}
                                    </p>
                                    <p className="text-xs text-muted-foreground sm:hidden truncate">{u.email}</p>
                                </div>
                            </div>

                            {/* Email */}
                            <p className="hidden sm:block text-sm text-muted-foreground truncate">{u.email}</p>

                            {/* Role */}
                            <RoleBadge role={u.role} />

                            {/* Actions */}
                            {isAdmin && (
                                <div className="flex items-center gap-1 justify-end">
                                    {u.id !== user?.id && (
                                        <>
                                            <Button variant="ghost" size="icon" className="h-8 w-8 text-muted-foreground hover:text-foreground"
                                                onClick={() => openEdit(u)} title="Editar usuário" data-testid={`edit-user-${u.id}`}>
                                                <Pencil className="h-3.5 w-3.5" />
                                            </Button>
                                            <Button variant="ghost" size="icon" className="h-8 w-8 text-muted-foreground hover:text-destructive"
                                                onClick={() => setDeleteTarget(u)} title="Remover usuário" data-testid={`remove-user-${u.id}`}>
                                                <Trash2 className="h-3.5 w-3.5" />
                                            </Button>
                                        </>
                                    )}
                                </div>
                            )}
                        </div>
                    ))}
                </div>
            </div>

            {/* Lead Sources section (admin only) */}
            {isAdmin && (
                <>
                    <Separator className="mb-8" />
                    <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-4">
                        <div>
                            <h2 className="text-lg font-heading font-semibold">Canais de Origem do Lead</h2>
                            <p className="text-sm text-muted-foreground mt-0.5">Gerencie os canais disponíveis no CRM</p>
                        </div>
                        <Button size="sm" variant="outline" onClick={() => setShowAddSource(true)} className="gap-1.5 shrink-0">
                            <Plus className="h-3.5 w-3.5" /> Novo Canal
                        </Button>
                    </div>

                    {lsLoading ? (
                        <div className="space-y-2">
                            {[1,2,3].map(i => <div key={i} className="h-10 bg-muted animate-pulse rounded-lg" />)}
                        </div>
                    ) : (
                        <div className="rounded-xl border border-border overflow-hidden">
                            <div className="divide-y divide-border">
                                {leadSources.length === 0 && (
                                    <div className="p-6 text-center text-sm text-muted-foreground">Nenhum canal cadastrado</div>
                                )}
                                {leadSources.map(src => (
                                    <div key={src.id} className={`flex flex-wrap items-center gap-3 p-3 sm:p-4 text-sm ${!src.ativo ? "opacity-50" : ""}`}>
                                        <code className="text-xs bg-muted px-2 py-1 rounded font-mono flex-shrink-0">{src.valor}</code>
                                        {editingSource === src.id ? (
                                            <div className="flex flex-wrap items-center gap-2 flex-1 min-w-0">
                                                <Input className="h-7 text-xs w-40" value={editSourceForm.nome}
                                                    onChange={e => setEditSourceForm(f => ({ ...f, nome: e.target.value }))} placeholder="Nome" />
                                                <Input className="h-7 text-xs w-32" value={editSourceForm.grupo}
                                                    onChange={e => setEditSourceForm(f => ({ ...f, grupo: e.target.value }))} placeholder="Grupo" />
                                                <Button size="sm" className="h-7 text-xs" onClick={() => updateLeadSource(src.id, editSourceForm)}>Salvar</Button>
                                                <Button size="sm" variant="ghost" className="h-7 text-xs" onClick={() => setEditingSource(null)}>Cancelar</Button>
                                            </div>
                                        ) : (
                                            <>
                                                <span className="flex-1 font-medium">{src.nome}</span>
                                                {src.grupo && <span className="text-xs text-muted-foreground hidden sm:inline">{src.grupo}</span>}
                                                <div className="flex items-center gap-2 ml-auto">
                                                    <button className="text-muted-foreground hover:text-foreground transition-colors"
                                                        onClick={() => { setEditingSource(src.id); setEditSourceForm({ nome: src.nome, grupo: src.grupo || "" }); }}
                                                        title="Editar canal">
                                                        <Pencil className="h-3.5 w-3.5" />
                                                    </button>
                                                    <button className={`transition-colors ${src.ativo ? "text-emerald-500 hover:text-emerald-600" : "text-muted-foreground hover:text-foreground"}`}
                                                        onClick={() => toggleLeadSource(src)}
                                                        title={src.ativo ? "Desativar" : "Ativar"}>
                                                        {src.ativo ? <ToggleRight className="h-5 w-5" /> : <ToggleLeft className="h-5 w-5" />}
                                                    </button>
                                                </div>
                                            </>
                                        )}
                                    </div>
                                ))}
                            </div>
                        </div>
                    )}
                </>
            )}

            {/* ── Modal: Invite ── */}
            <Dialog open={inviteOpen} onOpenChange={(o) => { setInviteOpen(o); if (!o) setInviteResult(null); }}>
                <DialogContent className="sm:max-w-md" data-testid="invite-dialog">
                    <DialogHeader>
                        <DialogTitle className="font-heading flex items-center gap-2">
                            <UserPlus className="h-5 w-5" />
                            {inviteResult ? "Usuário criado" : "Novo Usuário"}
                        </DialogTitle>
                    </DialogHeader>

                    {inviteResult ? (
                        <div className="space-y-4 py-2">
                            <div className="flex items-center gap-3 p-3 rounded-lg bg-emerald-50 dark:bg-emerald-950/30 border border-emerald-200 dark:border-emerald-800">
                                <div className="w-8 h-8 rounded-full bg-emerald-500 flex items-center justify-center">
                                    <UserAvatar name={inviteResult.name} size={32} />
                                </div>
                                <div>
                                    <p className="font-medium text-sm">{inviteResult.name}</p>
                                    <p className="text-xs text-muted-foreground">{inviteResult.email}</p>
                                </div>
                                <RoleBadge role={inviteResult.role} />
                            </div>

                            <div className="p-3 rounded-lg bg-muted/60 space-y-2">
                                <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Credenciais temporárias</p>
                                <div className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm">
                                    <span className="text-muted-foreground">Email</span>
                                    <span className="font-mono font-medium">{inviteResult.email}</span>
                                    <span className="text-muted-foreground">Senha</span>
                                    <span className="font-mono font-medium text-amber-600 dark:text-amber-400">{inviteResult.temp_password}</span>
                                </div>
                            </div>

                            <Button variant="outline" className="w-full gap-2" onClick={() => {
                                const text = `Email: ${inviteResult.email}\nSenha: ${inviteResult.temp_password}`;
                                navigator.clipboard?.writeText(text).then(() => toast.success("Copiado!")).catch(() => window.prompt("Copie manualmente:", text));
                            }} data-testid="copy-credentials-btn">
                                <Copy className="h-4 w-4" /> Copiar Credenciais
                            </Button>
                        </div>
                    ) : (
                        <div className="space-y-4 py-2">
                            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                                <div className="space-y-1.5 sm:col-span-2">
                                    <Label>Nome completo *</Label>
                                    <Input data-testid="invite-name" value={inviteForm.name}
                                        onChange={(e) => setInviteForm({ ...inviteForm, name: e.target.value })}
                                        placeholder="Ex: Maria Silva" />
                                </div>
                                <div className="space-y-1.5 sm:col-span-2">
                                    <Label>Email corporativo *</Label>
                                    <Input type="email" data-testid="invite-email" value={inviteForm.email}
                                        onChange={(e) => setInviteForm({ ...inviteForm, email: e.target.value })}
                                        placeholder="maria@empresa.com" />
                                </div>
                                <div className="space-y-1.5 sm:col-span-2">
                                    <Label>Perfil de acesso *</Label>
                                    <Select value={inviteForm.role} onValueChange={(v) => setInviteForm({ ...inviteForm, role: v })}>
                                        <SelectTrigger data-testid="invite-role">
                                            <SelectValue />
                                        </SelectTrigger>
                                        <SelectContent>
                                            {ROLES.map(r => (
                                                <SelectItem key={r.value} value={r.value}>{r.label}</SelectItem>
                                            ))}
                                        </SelectContent>
                                    </Select>
                                </div>
                            </div>
                            <p className="text-xs text-muted-foreground">
                                Uma senha temporária será gerada automaticamente.
                            </p>
                        </div>
                    )}

                    <DialogFooter>
                        {inviteResult ? (
                            <Button onClick={() => setInviteOpen(false)} className="w-full">Fechar</Button>
                        ) : (
                            <>
                                <Button variant="outline" onClick={() => setInviteOpen(false)}>Cancelar</Button>
                                <Button onClick={handleInvite} disabled={!inviteForm.email || !inviteForm.name || inviteSubmitting}
                                    data-testid="send-invite-btn">
                                    {inviteSubmitting ? "Criando..." : "Criar Usuário"}
                                </Button>
                            </>
                        )}
                    </DialogFooter>
                </DialogContent>
            </Dialog>

            {/* ── Modal: Edit ── */}
            <Dialog open={editOpen} onOpenChange={setEditOpen}>
                <DialogContent className="sm:max-w-md" data-testid="edit-user-dialog">
                    <DialogHeader>
                        <DialogTitle className="font-heading flex items-center gap-2">
                            <Pencil className="h-5 w-5" />
                            Editar Usuário
                        </DialogTitle>
                    </DialogHeader>

                    {editTarget && (
                        <div className="space-y-4 py-2">
                            <div className="flex items-center gap-3 p-3 rounded-lg bg-muted/50">
                                <UserAvatar name={editTarget.name} size={36} />
                                <div className="min-w-0">
                                    <p className="font-medium text-sm">{editTarget.name}</p>
                                    <p className="text-xs text-muted-foreground">{editTarget.email}</p>
                                </div>
                            </div>

                            <div className="space-y-1.5">
                                <Label>Nome completo</Label>
                                <Input value={editForm.name}
                                    onChange={(e) => setEditForm({ ...editForm, name: e.target.value })} />
                            </div>

                            <div className="space-y-1.5">
                                <Label>Perfil de acesso</Label>
                                <Select value={editForm.role} onValueChange={(v) => setEditForm({ ...editForm, role: v })}>
                                    <SelectTrigger>
                                        <SelectValue />
                                    </SelectTrigger>
                                    <SelectContent>
                                        {ROLES.map(r => (
                                            <SelectItem key={r.value} value={r.value}>{r.label}</SelectItem>
                                        ))}
                                    </SelectContent>
                                </Select>
                            </div>

                            <Separator />

                            <div className="space-y-1.5">
                                <Label className="flex items-center gap-1.5">
                                    <KeyRound className="h-3.5 w-3.5" />
                                    Nova senha
                                    <span className="text-muted-foreground font-normal">(opcional)</span>
                                </Label>
                                <Input type="password" placeholder="Deixe em branco para manter a atual"
                                    value={editForm.new_password}
                                    onChange={(e) => setEditForm({ ...editForm, new_password: e.target.value })} />
                                <p className="text-xs text-muted-foreground">Mínimo 6 caracteres</p>
                            </div>
                        </div>
                    )}

                    <DialogFooter>
                        <Button variant="outline" onClick={() => setEditOpen(false)}>Cancelar</Button>
                        <Button onClick={handleEdit} disabled={editSubmitting}>
                            {editSubmitting ? "Salvando..." : "Salvar Alterações"}
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>

            {/* ── Alert: Delete ── */}
            <AlertDialog open={!!deleteTarget} onOpenChange={(o) => !o && setDeleteTarget(null)}>
                <AlertDialogContent>
                    <AlertDialogHeader>
                        <AlertDialogTitle>Remover usuário?</AlertDialogTitle>
                        <AlertDialogDescription>
                            <strong>{deleteTarget?.name}</strong> perderá acesso ao sistema imediatamente.
                            Esta ação não pode ser desfeita.
                        </AlertDialogDescription>
                    </AlertDialogHeader>
                    <AlertDialogFooter>
                        <AlertDialogCancel>Cancelar</AlertDialogCancel>
                        <AlertDialogAction onClick={handleDelete}
                            className="bg-destructive text-destructive-foreground hover:bg-destructive/90">
                            Remover
                        </AlertDialogAction>
                    </AlertDialogFooter>
                </AlertDialogContent>
            </AlertDialog>

            {/* ── Modal: Add Lead Source ── */}
            <Dialog open={showAddSource} onOpenChange={setShowAddSource}>
                <DialogContent className="sm:max-w-sm">
                    <DialogHeader>
                        <DialogTitle className="font-heading">Novo Canal de Origem</DialogTitle>
                    </DialogHeader>
                    <div className="space-y-4 py-2">
                        <div className="space-y-1.5">
                            <Label>Nome de exibição *</Label>
                            <Input value={addSourceForm.nome}
                                onChange={e => setAddSourceForm(f => ({ ...f, nome: e.target.value }))}
                                placeholder="Ex: Indicação de parceiro" />
                        </div>
                        <div className="space-y-1.5">
                            <Label>Slug/valor * <span className="text-xs text-muted-foreground font-normal">(imutável)</span></Label>
                            <Input value={addSourceForm.valor}
                                onChange={e => setAddSourceForm(f => ({ ...f, valor: e.target.value.toLowerCase().replace(/\s+/g, "_").replace(/[^a-z0-9_]/g, "") }))}
                                placeholder="indicacao_parceiro" className="font-mono" />
                        </div>
                        <div className="space-y-1.5">
                            <Label>Grupo <span className="text-xs text-muted-foreground font-normal">(opcional)</span></Label>
                            <Input value={addSourceForm.grupo}
                                onChange={e => setAddSourceForm(f => ({ ...f, grupo: e.target.value }))}
                                placeholder="Ex: indicacao" />
                        </div>
                    </div>
                    <DialogFooter>
                        <Button variant="outline" onClick={() => setShowAddSource(false)}>Cancelar</Button>
                        <Button onClick={createLeadSource} disabled={!addSourceForm.nome || !addSourceForm.valor}>Criar Canal</Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        </div>
    );
}
