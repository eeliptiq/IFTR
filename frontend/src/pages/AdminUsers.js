import React, { useState, useEffect } from 'react';
import { useAuth } from '../contexts/AuthContext';
import { motion } from 'framer-motion';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Badge } from '../components/ui/badge';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '../components/ui/select';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '../components/ui/dialog';
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from '../components/ui/tabs';
import axios from 'axios';
import { toast } from 'sonner';
import {
  Users, Search, Shield, Truck, Store, Building2, User,
  CheckCircle, XCircle, Clock, History, RefreshCw,
  Mail, Phone, MapPin, Loader2, Filter, UserCheck, UserX,
  AlertTriangle, CreditCard, Lock,
} from 'lucide-react';

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

// The canonical UserRole values. The sign-up UI speaks in friendlier names, but
// the admin console talks to the API in the vocabulary the API stores.
const ROLES = [
  { id: 'customer', label: 'Customer' },
  { id: 'driver', label: 'Driver' },
  { id: 'restaurant_admin', label: 'Restaurant admin' },
  { id: 'organization_admin', label: 'Organization admin' },
  { id: 'support', label: 'Support' },
  { id: 'admin', label: 'Administrator' },
];

const ROLE_LABELS = Object.fromEntries(ROLES.map((role) => [role.id, role.label]));

const ROLE_STYLES = {
  customer: 'bg-gray-100 text-gray-700',
  driver: 'bg-blue-100 text-blue-700',
  restaurant_admin: 'bg-orange-100 text-orange-700',
  organization_admin: 'bg-purple-100 text-purple-700',
  support: 'bg-teal-100 text-teal-700',
  admin: 'bg-red-100 text-red-700',
};

const ROLE_ICONS = {
  customer: User,
  driver: Truck,
  restaurant_admin: Store,
  organization_admin: Building2,
  support: Clock,
  admin: Shield,
};

const ACTIONS = [
  { id: 'user.role_changed', label: 'Role changed' },
  { id: 'user.suspended', label: 'Account suspended' },
  { id: 'user.reactivated', label: 'Account reactivated' },
  { id: 'delivery.reassigned', label: 'Delivery returned to the pool' },
  { id: 'organization.verified', label: 'Organization verified' },
  { id: 'organization.unverified', label: 'Verification removed' },
];

const ACTION_LABELS = Object.fromEntries(ACTIONS.map((action) => [action.id, action.label]));

const formatDate = (value) => (value ? new Date(value).toLocaleString() : '—');

// `food_bank` reads as a database value; the screen should read as English.
const orgType = (value) => (value ? value.replace(/_/g, ' ') : 'organization');

const RoleBadge = ({ role }) => {
  const Icon = ROLE_ICONS[role] || User;
  return (
    <Badge className={ROLE_STYLES[role] || ROLE_STYLES.customer}>
      <Icon className="w-3 h-3 mr-1" />
      {ROLE_LABELS[role] || role}
    </Badge>
  );
};

// --------------------------------------------------------------------------
// Payment diagnostics
// --------------------------------------------------------------------------

// What the webhook route did with a delivery. `rejected` and `unconfigured`
// are the interesting ones: they mean Stripe arrived and the app could not
// believe it, which from outside looks exactly like nobody calling at all.
const OUTCOME_STYLES = {
  settled: 'bg-green-100 text-green-700',
  ignored: 'bg-gray-100 text-gray-700',
  unmatched: 'bg-amber-100 text-amber-700',
  unhandled: 'bg-gray-100 text-gray-700',
  rejected: 'bg-red-100 text-red-700',
  unconfigured: 'bg-amber-100 text-amber-700',
};

const KeyModeBadge = ({ diagnostics }) => {
  if (!diagnostics.configured) {
    return <Badge className="bg-gray-100 text-gray-700">Not configured</Badge>;
  }
  if (diagnostics.key_mode === 'unrecognised') {
    // A `pk_...` pasted where a secret key belongs: set, but not something
    // that can charge. Calling it "test mode" would be a lie.
    return <Badge className="bg-amber-100 text-amber-700">Unrecognised key</Badge>;
  }
  return diagnostics.live_mode ? (
    <Badge className="bg-red-600 text-white">Live — real cards</Badge>
  ) : (
    <Badge className="bg-green-100 text-green-700">Test mode</Badge>
  );
};

// The key's own words, never the key: which mode it charges in and whether it
// is a full or restricted key. An unrecognised shape gets its own label rather
// than being described as a key it is not.
const describeKey = (diagnostics) => {
  if (!diagnostics.configured) {
    return 'No key set — checkout answers 503 and orders stay payable';
  }
  const mode = { test: 'Test-mode', live: 'Live' }[diagnostics.key_mode];
  if (!mode) return 'Unrecognised key';
  const kind = diagnostics.key_kind === 'restricted' ? 'restricted key' : 'secret key';
  return `${mode} ${kind}`;
};

const SettingsRow = ({ label, children }) => (
  <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-1 py-2 border-b border-border/50 last:border-0">
    <p className="text-sm text-muted-foreground">{label}</p>
    <div className="text-sm font-medium sm:text-right sm:pl-6">{children}</div>
  </div>
);

// The banner is deliberately not dismissible. Both facts it reports are
// standing properties of the deployment, not events: a live key keeps charging
// real cards until somebody changes it, and events keep being refused until the
// signing secret exists. A dismissable warning would only be read once.
const PaymentsAlarm = ({ diagnostics, onOpen }) => {
  if (!diagnostics) return null;

  const live = diagnostics.live_mode;
  const unverified = diagnostics.configured && !diagnostics.webhook_secret_configured;
  if (!live && !unverified) return null;

  const reasons = [];
  if (live) {
    reasons.push(
      'STRIPE_SECRET_KEY is a live key: every Pay button charges a real card, and '
      + 'Stripe\'s test card numbers are declined.'
    );
  }
  if (unverified) {
    reasons.push(
      'STRIPE_WEBHOOK_SECRET is empty: Stripe\'s events are answered 503, so a payment '
      + 'is only confirmed while the customer\'s success page is still open.'
    );
  }

  return (
    <div
      role="alert"
      data-testid="payments-alarm"
      className="rounded-2xl border-2 border-destructive bg-destructive/10 p-4 md:p-5"
    >
      <div className="flex flex-col sm:flex-row sm:items-start gap-3">
        <div className="flex items-start gap-3 flex-1">
          <AlertTriangle className="w-6 h-6 text-destructive shrink-0 mt-0.5" />
          <div className="space-y-2">
            <p className="font-semibold text-destructive">
              {live && unverified
                ? 'Live payments with unverifiable webhooks'
                : live
                  ? 'This deployment charges real cards'
                  : 'Stripe\'s notifications cannot be verified'}
            </p>
            {reasons.map((reason) => (
              <p key={reason} className="text-sm text-foreground/90">{reason}</p>
            ))}
          </div>
        </div>
        <Button
          variant="outline"
          onClick={onOpen}
          className="shrink-0 border-destructive/40 text-destructive hover:text-destructive"
          data-testid="payments-alarm-open"
        >
          <CreditCard className="w-4 h-4 mr-2" />
          Payment diagnostics
        </Button>
      </div>
    </div>
  );
};

const PaymentsTab = ({ diagnostics, error, loading, onRetry }) => {
  if (loading && !diagnostics) {
    return (
      <Card>
        <CardContent className="p-12 text-center text-muted-foreground">
          <Loader2 className="w-6 h-6 mx-auto mb-2 animate-spin" />
          Reading this deployment's payment configuration...
        </CardContent>
      </Card>
    );
  }

  if (error) {
    return (
      <Card className="border-destructive/40">
        <CardContent className="p-8 text-center space-y-3">
          <AlertTriangle className="w-10 h-10 text-destructive mx-auto" />
          <p className="font-medium">Could not read the payment configuration</p>
          <p className="text-sm text-muted-foreground">{error}</p>
          <Button variant="outline" onClick={onRetry}>Try again</Button>
        </CardContent>
      </Card>
    );
  }

  if (!diagnostics) {
    return (
      <Card>
        <CardContent className="p-8 text-center space-y-3">
          <p className="text-sm text-muted-foreground">Nothing has been read yet.</p>
          <Button variant="outline" onClick={onRetry}>Load payment diagnostics</Button>
        </CardContent>
      </Card>
    );
  }

  const activity = diagnostics.webhook || {};
  const warnings = diagnostics.warnings || [];

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle className="flex flex-wrap items-center gap-2">
            <CreditCard className="w-5 h-5 text-primary" />
            Stripe settings
            <KeyModeBadge diagnostics={diagnostics} />
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-1">
          <SettingsRow label="Key">{describeKey(diagnostics)}</SettingsRow>
          <SettingsRow label="Checkout">
            {diagnostics.checkout_available
              ? 'Available — orders can be paid'
              : 'Not available — the Pay button explains why'}
          </SettingsRow>
          <SettingsRow label="Signing secret">
            {diagnostics.webhook_secret_configured ? (
              <span className="flex items-center gap-1 justify-end text-green-700">
                <CheckCircle className="w-4 h-4" />
                Events are verified
              </span>
            ) : (
              <span className="flex items-center gap-1 justify-end text-amber-700">
                <XCircle className="w-4 h-4" />
                Not set — events are refused with 503
              </span>
            )}
          </SettingsRow>
          <SettingsRow label="Webhook address">
            <code className="font-mono text-xs">{diagnostics.webhook_path}</code>
          </SettingsRow>
          <SettingsRow label="Charge">
            {(diagnostics.currency || 'usd').toUpperCase()}
            {' · minimum '}
            {diagnostics.min_charge_cents || 0}
            {'¢'}
          </SettingsRow>
          <SettingsRow label="Events acted on">
            <span className="font-mono text-xs">
              {(diagnostics.handled_events || []).join(', ') || '—'}
            </span>
          </SettingsRow>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Clock className="w-5 h-5 text-primary" />
            Webhook deliveries
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-1">
          <SettingsRow label="Last received">
            {activity.last_received_at ? (
              formatDate(activity.last_received_at)
            ) : (
              <span className="text-muted-foreground">Nothing has arrived yet</span>
            )}
          </SettingsRow>
          <SettingsRow label="Last event">
            {activity.last_event_type || '—'}
          </SettingsRow>
          <SettingsRow label="Last outcome">
            {activity.last_outcome ? (
              <Badge className={OUTCOME_STYLES[activity.last_outcome] || OUTCOME_STYLES.ignored}>
                {activity.last_outcome.replace(/_/g, ' ')}
              </Badge>
            ) : '—'}
          </SettingsRow>
          <SettingsRow label="Last verified delivery">
            {formatDate(activity.last_verified_at)}
          </SettingsRow>
          <SettingsRow label="Last refused delivery">
            {formatDate(activity.last_rejected_at)}
          </SettingsRow>
          <SettingsRow label="Last 24 hours">
            {activity.received_24h || 0} received
            {activity.rejected_24h ? ` · ${activity.rejected_24h} refused` : ''}
          </SettingsRow>
        </CardContent>
        {!activity.last_received_at && (diagnostics.configured) && (
          <CardContent className="pt-0">
            <p className="text-sm text-muted-foreground">
              Nothing has called the webhook yet. Locally that is
              {' '}
              <code className="font-mono text-xs">stripe listen --forward-to localhost:8000{diagnostics.webhook_path}</code>
              {' '}— <code className="font-mono text-xs">dev_payments.sh</code> starts it for you.
            </p>
          </CardContent>
        )}
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <AlertTriangle className="w-5 h-5 text-amber-600" />
            Warnings ({warnings.length})
          </CardTitle>
        </CardHeader>
        <CardContent>
          {warnings.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              Nothing to warn about: the settings above are consistent with each other.
            </p>
          ) : (
            <ul className="space-y-2">
              {warnings.map((warning) => (
                <li key={warning} className="flex items-start gap-2 text-sm">
                  <AlertTriangle className="w-4 h-4 text-amber-600 mt-0.5 shrink-0" />
                  <span>{warning}</span>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      <p className="text-xs text-muted-foreground flex items-start gap-2">
        <Lock className="w-3.5 h-3.5 mt-0.5 shrink-0" />
        Read at {formatDate(diagnostics.checked_at)} from this server's environment and its
        webhook delivery log. It never calls Stripe and never returns the key — only whether
        one is set, whether it is a test or a live one, and whether it is restricted. A refused
        delivery with no verified one beside it usually means the signing secret came from a
        different place than the events it is meant to verify.
      </p>
    </div>
  );
};

const AdminUsers = () => {
  const { token, user, checkAuth } = useAuth();
  const [users, setUsers] = useState([]);
  const [organizations, setOrganizations] = useState([]);
  const [events, setEvents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState('users');
  const [search, setSearch] = useState('');
  const [roleFilter, setRoleFilter] = useState('all');
  const [auditAction, setAuditAction] = useState('all');
  const [auditSubject, setAuditSubject] = useState('');
  const [auditLoading, setAuditLoading] = useState(false);
  const [savingRole, setSavingRole] = useState(null);
  const [accountBusy, setAccountBusy] = useState(null);
  const [orgBusy, setOrgBusy] = useState(null);
  const [confirmUnverify, setConfirmUnverify] = useState(null);
  const [confirmSuspend, setConfirmSuspend] = useState(null);
  // Read once on open so the alarm can fire without the admin having to go
  // looking for it; the Payments tab shows the same payload in full.
  const [diagnostics, setDiagnostics] = useState(null);
  const [diagnosticsError, setDiagnosticsError] = useState('');
  const [diagnosticsLoading, setDiagnosticsLoading] = useState(false);

  const headers = { Authorization: `Bearer ${token}` };
  const isAdmin = user?.role === 'admin';

  // A 403 can mean the role was revoked in another tab. Re-read the account
  // before reporting an error: if the role is gone, the refusal branch below
  // takes over, and a toast would only cover the same news.
  const reportAdminError = async (error, fallback) => {
    if (error.response?.status === 403) {
      const refreshed = await checkAuth();
      if (refreshed?.role === 'admin') {
        toast.error(error.response?.data?.detail || fallback);
      }
      return;
    }
    toast.error(error.response?.data?.detail || fallback);
  };

  useEffect(() => {
    if (!isAdmin) {
      setLoading(false);
      return;
    }
    fetchData();
    fetchDiagnostics();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAdmin]);

  const fetchData = async () => {
    try {
      const [usersRes, orgsRes] = await Promise.all([
        axios.get(`${API}/admin/users`, { headers, withCredentials: true }),
        axios.get(`${API}/admin/organizations`, { headers, withCredentials: true }),
      ]);
      setUsers(usersRes.data);
      setOrganizations(orgsRes.data);
    } catch (error) {
      await reportAdminError(error, 'Failed to load the admin console');
    } finally {
      setLoading(false);
    }
  };

  const fetchDiagnostics = async () => {
    setDiagnosticsLoading(true);
    setDiagnosticsError('');
    try {
      const response = await axios.get(`${API}/payments/diagnostics`, {
        headers,
        withCredentials: true,
      });
      setDiagnostics(response.data);
    } catch (error) {
      // A quiet error state rather than a toast: this read happens on page
      // open, and a toast would announce a background failure as if the admin
      // had just done something. The panel shows the reason with a retry.
      setDiagnosticsError(
        error.response?.data?.detail || 'Could not read the payment configuration'
      );
    } finally {
      setDiagnosticsLoading(false);
    }
  };

  const fetchAudit = async (action = auditAction, subject = auditSubject) => {
    setAuditLoading(true);
    try {
      const params = { limit: 100 };
      if (action !== 'all') params.action = action;
      if (subject.trim()) params.subject_id = subject.trim();
      const response = await axios.get(`${API}/admin/audit`, {
        headers,
        withCredentials: true,
        params,
      });
      setEvents(response.data);
    } catch (error) {
      await reportAdminError(error, 'Failed to load the audit trail');
    } finally {
      setAuditLoading(false);
    }
  };

  useEffect(() => {
    if (isAdmin && tab === 'audit') fetchAudit();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAdmin, tab]);

  const changeRole = async (target, role) => {
    if (role === target.role) return;
    setSavingRole(target.user_id);
    try {
      const response = await axios.put(
        `${API}/admin/users/${target.user_id}/role`,
        { role },
        { headers, withCredentials: true }
      );
      setUsers((rows) => rows.map((row) => (
        row.user_id === target.user_id ? { ...row, role: response.data.role } : row
      )));
      toast.success(`${target.name || target.email} is now ${ROLE_LABELS[role] || role}`);
      // Changing your own role changes what the sidebar and this page may show,
      // so re-read the account before the next click.
      if (target.user_id === user?.user_id) await checkAuth();
    } catch (error) {
      await reportAdminError(error, 'Failed to change role');
    } finally {
      setSavingRole(null);
    }
  };

  const setSuspension = async (account, active) => {
    setAccountBusy(account.user_id);
    try {
      const response = await axios.put(
        `${API}/admin/users/${account.user_id}/active`,
        { is_active: active },
        { headers, withCredentials: true }
      );
      setUsers((rows) => rows.map((row) => (
        row.user_id === account.user_id
          ? { ...row, is_active: response.data.is_active }
          : row
      )));
      const released = response.data.released_deliveries || 0;
      toast.success(active
        ? `${account.name || account.email} can sign in again`
        : `${account.name || account.email} is suspended${
          released
            ? `; ${released} delivery ${released === 1 ? 'is' : 'are'} back on the board`
            : ''
        }`);
      setConfirmSuspend(null);
      // Suspending yourself ends this session with the suspension; re-reading
      // the account lets the route show the same refusal as any other session.
      if (!active && account.user_id === user?.user_id) await checkAuth();
    } catch (error) {
      await reportAdminError(error, active
        ? 'Failed to reactivate account'
        : 'Failed to suspend account');
    } finally {
      setAccountBusy(null);
    }
  };

  const setVerification = async (organization, verified) => {
    setOrgBusy(organization.org_id);
    try {
      if (verified) {
        await axios.put(
          `${API}/admin/organizations/${organization.org_id}/verify`,
          {},
          { headers, withCredentials: true }
        );
      } else {
        await axios.delete(
          `${API}/admin/organizations/${organization.org_id}/verify`,
          { headers, withCredentials: true }
        );
      }
      setOrganizations((rows) => rows.map((row) => (
        row.org_id === organization.org_id
          ? { ...row, is_verified: verified }
          : row
      )));
      toast.success(verified
        ? `${organization.name} can now reserve surplus food`
        : `${organization.name} can no longer reserve surplus food`);
      setConfirmUnverify(null);
    } catch (error) {
      await reportAdminError(error, 'Failed to update verification');
    } finally {
      setOrgBusy(null);
    }
  };

  // A suspended administrator holds the role but cannot act, so the guard and
  // the summary count only the ones who can sign in.
  const activeAdministrators = users.filter(
    (account) => account.role === 'admin' && account.is_active !== false
  ).length;

  const filteredUsers = users.filter((account) => {
    const matchesRole = roleFilter === 'all' || account.role === roleFilter;
    const needle = search.trim().toLowerCase();
    const matchesSearch = !needle
      || account.name?.toLowerCase().includes(needle)
      || account.email?.toLowerCase().includes(needle);
    return matchesRole && matchesSearch;
  });

  const pendingOrganizations = organizations.filter((organization) => !organization.is_verified);
  const verifiedOrganizations = organizations.filter((organization) => organization.is_verified);

  const subjectName = (subjectId) => {
    const account = users.find((row) => row.user_id === subjectId);
    if (account) return account.name || account.email;
    const organization = organizations.find((row) => row.org_id === subjectId);
    if (organization) return organization.name;
    return subjectId;
  };

  const actorName = (event) => {
    if (event.actor_kind === 'cli') return 'Operator (server shell)';
    if (!event.actor_id) return 'System';
    const account = users.find((row) => row.user_id === event.actor_id);
    return account ? (account.name || account.email) : event.actor_id;
  };

  if (loading) {
    return (
      <div className="p-6 md:p-8">
        <div className="animate-pulse space-y-6">
          <div className="h-8 bg-muted rounded w-1/3" />
          <div className="h-64 bg-muted rounded-xl" />
        </div>
      </div>
    );
  }

  if (!isAdmin) {
    return (
      <div className="p-6 md:p-8">
        <Card>
          <CardContent className="p-12 text-center">
            <Shield className="w-12 h-12 text-muted-foreground mx-auto mb-4" />
            <p className="font-medium">Administrator access required</p>
            <p className="text-sm text-muted-foreground mt-1">
              This console changes roles, account status and verification, so only an
              administrator can open it.
            </p>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="p-6 md:p-8 space-y-6" data-testid="admin-users-page">
      <div className="flex flex-col sm:flex-row sm:items-end justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight flex items-center gap-3">
            <Shield className="w-8 h-8 text-primary" />
            Admin Console
          </h1>
          <p className="text-muted-foreground">
            Roles, account suspension, organization verification, and the trail of all three
          </p>
        </div>
        <Button
          variant="outline"
          onClick={() => {
            fetchData();
            fetchDiagnostics();
            if (tab === 'audit') fetchAudit();
          }}
          data-testid="refresh-admin"
        >
          <RefreshCw className="w-4 h-4 mr-2" />
          Refresh
        </Button>
      </div>

      <PaymentsAlarm
        diagnostics={diagnostics}
        onOpen={() => setTab('payments')}
      />

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <Card>
          <CardContent className="p-4 text-center">
            <p className="text-2xl font-bold">{users.length}</p>
            <p className="text-sm text-muted-foreground">Accounts</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4 text-center">
            <p className="text-2xl font-bold text-amber-600">{pendingOrganizations.length}</p>
            <p className="text-sm text-muted-foreground">Pending organizations</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4 text-center">
            <p className="text-2xl font-bold text-green-600">{verifiedOrganizations.length}</p>
            <p className="text-sm text-muted-foreground">Verified organizations</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4 text-center">
            <p className="text-2xl font-bold text-red-600">{activeAdministrators}</p>
            <p className="text-sm text-muted-foreground">Active administrators</p>
          </CardContent>
        </Card>
      </div>

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList className="grid grid-cols-2 sm:grid-cols-4 w-full sm:w-auto">
          <TabsTrigger value="users" data-testid="admin-tab-users">
            <Users className="w-4 h-4 mr-2" />
            Users ({users.length})
          </TabsTrigger>
          <TabsTrigger value="organizations" data-testid="admin-tab-organizations">
            <Building2 className="w-4 h-4 mr-2" />
            Organizations ({organizations.length})
          </TabsTrigger>
          <TabsTrigger value="audit" data-testid="admin-tab-audit">
            <History className="w-4 h-4 mr-2" />
            Audit trail
          </TabsTrigger>
          <TabsTrigger value="payments" data-testid="admin-tab-payments">
            <CreditCard className="w-4 h-4 mr-2" />
            Payments
          </TabsTrigger>
        </TabsList>

        {/* Users ----------------------------------------------------------------- */}
        <TabsContent value="users" className="space-y-4 mt-4">
          <div className="flex flex-col sm:flex-row gap-4">
            <div className="relative flex-1">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-muted-foreground" />
              <Input
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="Search by name or email..."
                className="pl-10"
                data-testid="search-users"
              />
            </div>
            <Select value={roleFilter} onValueChange={setRoleFilter}>
              <SelectTrigger className="w-full sm:w-56" data-testid="filter-role">
                <Filter className="w-4 h-4 mr-2" />
                <SelectValue placeholder="Filter by role" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All roles</SelectItem>
                {ROLES.map((role) => (
                  <SelectItem key={role.id} value={role.id}>{role.label}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <Card>
            <CardContent className="p-0">
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead>
                    <tr className="border-b border-border">
                      <th className="text-left p-4 font-medium text-muted-foreground">User</th>
                      <th className="text-left p-4 font-medium text-muted-foreground">Role</th>
                      <th className="text-left p-4 font-medium text-muted-foreground">Status</th>
                      <th className="text-left p-4 font-medium text-muted-foreground">Joined</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredUsers.map((account, index) => (
                      <motion.tr
                        key={account.user_id}
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        transition={{ delay: index * 0.02 }}
                        className="border-b border-border/50 hover:bg-secondary/30"
                      >
                        <td className="p-4">
                          <div className="flex items-center gap-3">
                            <div className="w-10 h-10 rounded-full bg-primary/10 flex items-center justify-center">
                              {React.createElement(ROLE_ICONS[account.role] || User, {
                                className: 'w-4 h-4',
                              })}
                            </div>
                            <div>
                              <p className="font-medium">{account.name || 'Unnamed'}</p>
                              <p className="text-sm text-muted-foreground">{account.email}</p>
                            </div>
                          </div>
                        </td>
                        <td className="p-4">
                          <div className="space-y-2">
                            <RoleBadge role={account.role} />
                            <Select
                              value={account.role}
                              onValueChange={(value) => changeRole(account, value)}
                              disabled={
                                savingRole === account.user_id
                                || accountBusy === account.user_id
                              }
                            >
                              <SelectTrigger
                                className="w-[210px]"
                                data-testid={`role-select-${account.user_id}`}
                              >
                                {savingRole === account.user_id ? (
                                  <span className="flex items-center gap-2 text-sm">
                                    <Loader2 className="w-4 h-4 animate-spin" />
                                    Saving...
                                  </span>
                                ) : (
                                  <SelectValue />
                                )}
                              </SelectTrigger>
                              <SelectContent>
                                {ROLES.map((role) => (
                                  <SelectItem key={role.id} value={role.id}>
                                    {role.label}
                                  </SelectItem>
                                ))}
                              </SelectContent>
                            </Select>
                          </div>
                        </td>
                        <td className="p-4">
                          <div className="space-y-2">
                            {account.is_active === false ? (
                              <Badge className="bg-red-100 text-red-700">Suspended</Badge>
                            ) : account.is_approved === false ? (
                              <Badge className="bg-amber-100 text-amber-700">Awaiting approval</Badge>
                            ) : (
                              <Badge className="bg-green-100 text-green-700">Active</Badge>
                            )}
                            <Button
                              variant="outline"
                              size="sm"
                              onClick={() => (
                                account.is_active === false
                                  ? setSuspension(account, true)
                                  : setConfirmSuspend(account)
                              )}
                              disabled={accountBusy === account.user_id}
                              data-testid={
                                `${account.is_active === false ? 'reactivate' : 'suspend'}-user-${account.user_id}`
                              }
                            >
                              {accountBusy === account.user_id ? (
                                <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                              ) : account.is_active === false ? (
                                <UserCheck className="w-4 h-4 mr-2" />
                              ) : (
                                <UserX className="w-4 h-4 mr-2" />
                              )}
                              {account.is_active === false ? 'Reactivate' : 'Suspend'}
                            </Button>
                          </div>
                        </td>
                        <td className="p-4 text-muted-foreground">
                          {formatDate(account.created_at)}
                        </td>
                      </motion.tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {filteredUsers.length === 0 && (
                <div className="p-12 text-center">
                  <Users className="w-12 h-12 text-muted-foreground mx-auto mb-4" />
                  <p className="text-muted-foreground">No accounts match these filters</p>
                </div>
              )}
            </CardContent>
          </Card>

          <p className="text-xs text-muted-foreground">
            The last active administrator cannot be demoted or suspended. Suspension blocks
            sign-in and existing sessions without changing the role, the restaurant,
            organization or driver record the account owns. A suspended driver's accepted
            orders and claimed volunteer runs return to the board; work already collected
            must be resolved before the account can be suspended.
          </p>
        </TabsContent>

        {/* Organizations --------------------------------------------------------- */}
        <TabsContent value="organizations" className="space-y-6 mt-4">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Clock className="w-5 h-5 text-amber-600" />
                Pending verification ({pendingOrganizations.length})
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              {pendingOrganizations.length === 0 ? (
                <p className="text-sm text-muted-foreground py-4">
                  Nothing waiting — every organization has been reviewed.
                </p>
              ) : pendingOrganizations.map((organization) => (
                <div
                  key={organization.org_id}
                  className="p-4 rounded-xl border border-amber-500/30 bg-amber-500/5 space-y-3"
                  data-testid={`pending-org-${organization.org_id}`}
                >
                  <div className="flex flex-col md:flex-row md:items-start justify-between gap-3">
                    <div>
                      <p className="font-semibold">{organization.name}</p>
                      <p className="text-sm text-muted-foreground capitalize">
                        {orgType(organization.org_type)} • applied {formatDate(organization.created_at)}
                      </p>
                    </div>
                    <Button
                      onClick={() => setVerification(organization, true)}
                      disabled={orgBusy === organization.org_id}
                      className="bg-green-600 hover:bg-green-700"
                      data-testid={`verify-org-${organization.org_id}`}
                    >
                      {orgBusy === organization.org_id ? (
                        <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                      ) : (
                        <CheckCircle className="w-4 h-4 mr-2" />
                      )}
                      Verify
                    </Button>
                  </div>
                  <div className="grid sm:grid-cols-2 gap-2 text-sm">
                    <p className="flex items-center gap-2 text-muted-foreground">
                      <Mail className="w-4 h-4" />
                      {organization.contact_email || 'No contact email'}
                    </p>
                    <p className="flex items-center gap-2 text-muted-foreground">
                      <Phone className="w-4 h-4" />
                      {organization.contact_phone || 'No phone'}
                    </p>
                    <p className="flex items-center gap-2 text-muted-foreground">
                      <MapPin className="w-4 h-4" />
                      {[organization.address, organization.city].filter(Boolean).join(', ') || 'No address'}
                    </p>
                    <p className="flex items-center gap-2 text-muted-foreground">
                      <User className="w-4 h-4" />
                      Owner: {organization.owner_name || 'Unknown'}
                      {organization.owner_email ? ` (${organization.owner_email})` : ''}
                    </p>
                  </div>
                  {organization.description && (
                    <p className="text-sm text-muted-foreground">{organization.description}</p>
                  )}
                </div>
              ))}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <CheckCircle className="w-5 h-5 text-green-600" />
                Verified organizations ({verifiedOrganizations.length})
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              {verifiedOrganizations.length === 0 ? (
                <p className="text-sm text-muted-foreground py-4">No verified organizations yet.</p>
              ) : verifiedOrganizations.map((organization) => (
                <div
                  key={organization.org_id}
                  className="p-4 rounded-xl border border-border flex flex-col sm:flex-row sm:items-center justify-between gap-3"
                  data-testid={`verified-org-${organization.org_id}`}
                >
                  <div>
                    <p className="font-semibold">{organization.name}</p>
                    <p className="text-sm text-muted-foreground">
                      {organization.contact_email || 'No contact email'}
                      {' • '}
                      {organization.total_received} portion(s) received
                    </p>
                  </div>
                  <Button
                    variant="outline"
                    onClick={() => setConfirmUnverify(organization)}
                    disabled={orgBusy === organization.org_id}
                    className="text-destructive hover:text-destructive"
                    data-testid={`unverify-org-${organization.org_id}`}
                  >
                    <XCircle className="w-4 h-4 mr-2" />
                    Remove verification
                  </Button>
                </div>
              ))}
            </CardContent>
          </Card>
        </TabsContent>

        {/* Audit ----------------------------------------------------------------- */}
        <TabsContent value="audit" className="space-y-4 mt-4">
          <div className="flex flex-col sm:flex-row gap-3">
            <Select
              value={auditAction}
              onValueChange={(value) => {
                setAuditAction(value);
                fetchAudit(value, auditSubject);
              }}
            >
              <SelectTrigger className="w-full sm:w-64" data-testid="audit-action-filter">
                <Filter className="w-4 h-4 mr-2" />
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All actions</SelectItem>
                {ACTIONS.map((action) => (
                  <SelectItem key={action.id} value={action.id}>{action.label}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Input
              value={auditSubject}
              onChange={(event) => setAuditSubject(event.target.value)}
              placeholder="Filter by account or organization id"
              className="flex-1"
              data-testid="audit-subject-filter"
            />
            <Button
              variant="outline"
              onClick={() => fetchAudit()}
              disabled={auditLoading}
              data-testid="audit-refresh"
            >
              {auditLoading ? (
                <Loader2 className="w-4 h-4 mr-2 animate-spin" />
              ) : (
                <RefreshCw className="w-4 h-4 mr-2" />
              )}
              Apply
            </Button>
          </div>

          <Card>
            <CardContent className="p-0">
              {auditLoading && events.length === 0 ? (
                <div className="p-12 text-center text-muted-foreground">
                  <Loader2 className="w-6 h-6 mx-auto mb-2 animate-spin" />
                  Loading the trail...
                </div>
              ) : events.length === 0 ? (
                <div className="p-12 text-center">
                  <History className="w-12 h-12 text-muted-foreground mx-auto mb-4" />
                  <p className="text-muted-foreground">No audit entries match these filters</p>
                </div>
              ) : (
                <div className="divide-y divide-border">
                  {events.map((event) => (
                    <div
                      key={event.event_id}
                      className="p-4 flex flex-col md:flex-row md:items-start justify-between gap-3"
                      data-testid="audit-entry"
                      data-event-id={event.event_id}
                    >
                      <div className="space-y-1">
                        <div className="flex items-center gap-2 flex-wrap">
                          <Badge className="bg-secondary text-foreground">
                            {ACTION_LABELS[event.action] || event.action}
                          </Badge>
                          <span className="text-sm font-medium">
                            {subjectName(event.subject_id)}
                          </span>
                          {event.from_value !== null || event.to_value !== null ? (
                            <span className="text-sm text-muted-foreground">
                              {event.from_value || 'none'} → {event.to_value || 'none'}
                            </span>
                          ) : null}
                        </div>
                        <p className="text-sm text-muted-foreground">
                          {event.detail || '—'}
                        </p>
                        <p className="text-xs text-muted-foreground font-mono">
                          {event.subject_id}
                        </p>
                      </div>
                      <div className="text-left md:text-right text-sm shrink-0">
                        <p className="font-medium">{actorName(event)}</p>
                        <p className="text-muted-foreground">
                          {event.actor_kind === 'cli'
                            ? 'operator'
                            : (ROLE_LABELS[event.actor_role] || event.actor_role || 'unknown role')}
                        </p>
                        <p className="text-xs text-muted-foreground">
                          {formatDate(event.created_at)}
                        </p>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        {/* Payments -------------------------------------------------------------- */}
        <TabsContent value="payments" className="mt-4">
          <PaymentsTab
            diagnostics={diagnostics}
            error={diagnosticsError}
            loading={diagnosticsLoading}
            onRetry={fetchDiagnostics}
          />
        </TabsContent>
      </Tabs>

      <Dialog
        open={!!confirmUnverify}
        onOpenChange={(open) => { if (!open) setConfirmUnverify(null); }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Remove verification?</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 mt-2">
            <p className="text-sm text-muted-foreground">
              <strong>{confirmUnverify?.name}</strong> will not be able to reserve surplus
              food. Runs already accepted keep going, so food in hand is not stranded.
            </p>
            <div className="flex gap-3">
              <Button
                variant="outline"
                className="flex-1"
                onClick={() => setConfirmUnverify(null)}
              >
                Cancel
              </Button>
              <Button
                className="flex-1 bg-destructive hover:bg-destructive/90"
                disabled={orgBusy === confirmUnverify?.org_id}
                onClick={() => setVerification(confirmUnverify, false)}
                data-testid="confirm-unverify"
              >
                {orgBusy === confirmUnverify?.org_id ? (
                  <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                ) : (
                  <XCircle className="w-4 h-4 mr-2" />
                )}
                Remove verification
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      <Dialog
        open={!!confirmSuspend}
        onOpenChange={(open) => { if (!open) setConfirmSuspend(null); }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Suspend account?</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 mt-2">
            <p className="text-sm text-muted-foreground">
              <strong>{confirmSuspend?.name || confirmSuspend?.email}</strong> will be
              signed out and blocked from signing in until an administrator reactivates
              the account. Their role, restaurant, organization and driver records stay
              exactly as they are. A delivery they have accepted but not yet collected
              goes back to the available pool; one already in hand must be finished
              first.
            </p>
            <div className="flex gap-3">
              <Button
                variant="outline"
                className="flex-1"
                onClick={() => setConfirmSuspend(null)}
              >
                Cancel
              </Button>
              <Button
                className="flex-1 bg-destructive hover:bg-destructive/90"
                disabled={accountBusy === confirmSuspend?.user_id}
                onClick={() => setSuspension(confirmSuspend, false)}
                data-testid="confirm-suspend"
              >
                {accountBusy === confirmSuspend?.user_id ? (
                  <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                ) : (
                  <UserX className="w-4 h-4 mr-2" />
                )}
                Suspend account
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
};

export default AdminUsers;
