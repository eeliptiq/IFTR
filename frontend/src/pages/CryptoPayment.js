import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useParams, useNavigate, Link } from 'react-router-dom';
import axios from 'axios';
import { toast } from 'sonner';
import { QRCodeSVG } from 'qrcode.react';
import { useAuth } from '../contexts/AuthContext';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Badge } from '../components/ui/badge';
import {
  AlertTriangle,
  ArrowLeft,
  Bitcoin,
  Check,
  CheckCircle,
  Clock,
  Coins,
  Copy,
  Loader2,
  RefreshCw,
} from 'lucide-react';

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

// The page is the only thing watching an open invoice in the browser; the
// server's background sweep is what catches a payment made with the tab closed.
// Polling every few seconds is fast enough for a human deciding to pay and slow
// enough not to hammer a wallet that is also being swept.
const POLL_INTERVAL_MS = 4000;

const formatClock = (seconds) => {
  const safe = Math.max(0, seconds);
  const minutes = Math.floor(safe / 60);
  const rest = safe % 60;
  return `${minutes}:${String(rest).padStart(2, '0')}`;
};

const formatDollars = (cents) =>
  `$${(Number(cents || 0) / 100).toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;

const AssetIcon = ({ code }) =>
  code === 'btc' ? <Bitcoin className="w-4 h-4" /> : <Coins className="w-4 h-4" />;

const CryptoPayment = () => {
  const { orderId } = useParams();
  const navigate = useNavigate();
  const { token } = useAuth();

  const [methods, setMethods] = useState(null);
  const [asset, setAsset] = useState('');
  const [invoice, setInvoice] = useState(null);
  const [status, setStatus] = useState(null);
  const [error, setError] = useState('');
  const [starting, setStarting] = useState(false);
  const [now, setNow] = useState(() => Date.now());
  const [copied, setCopied] = useState('');
  const [paid, setPaid] = useState(false);

  // Both the invoice request and the polling chain check this after every
  // await: a customer who leaves the page must not have state set under them.
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const authHeaders = useCallback(
    () => (token ? { Authorization: `Bearer ${token}` } : {}),
    [token]
  );

  // Which coins this deployment can take. A deployment with no wallet answers
  // with an empty list and the page says so rather than offering a dead button.
  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const res = await axios.get(`${API}/payments/methods`, {
          headers: authHeaders(),
          withCredentials: true,
        });
        if (cancelled) return;
        setMethods(res.data);
        const available = res.data?.crypto?.assets || [];
        if (available.length && !asset) {
          setAsset(available[0].code);
        }
      } catch (err) {
        if (cancelled) return;
        setError(
          err.response?.data?.detail ||
            'Could not ask the server which payment methods are available.'
        );
      }
    };
    load();
    return () => {
      cancelled = true;
    };
    // `asset` is read once on purpose: the default is chosen from the first
    // answer and never overwritten afterwards.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [authHeaders]);

  const openInvoice = useCallback(
    async (code) => {
      setStarting(true);
      setError('');
      try {
        const res = await axios.post(
          `${API}/payments/crypto/invoice`,
          { order_id: orderId, asset: code },
          { headers: authHeaders(), withCredentials: true }
        );
        if (!mounted.current) return;
        setInvoice(res.data);
        setStatus(null);
        setPaid(false);
      } catch (err) {
        if (!mounted.current) return;
        const detail = err.response?.data?.detail;
        if (err.response?.status === 409 && /already paid/i.test(detail || '')) {
          setPaid(true);
        }
        setError(detail || 'The invoice could not be opened. Nothing was charged.');
      } finally {
        if (mounted.current) setStarting(false);
      }
    },
    [orderId, authHeaders]
  );

  // One invoice per asset choice: asking again after one appears would either
  // return the same address (the server is idempotent) or replace a quote the
  // customer is already typing into a wallet. Changing coin goes through
  // `chooseAsset`, which asks for the new one explicitly.
  useEffect(() => {
    if (asset && !invoice) {
      openInvoice(asset);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [asset]);

  const chooseAsset = (code) => {
    if (invoice) {
      // Only reachable once the quote is over: a live one keeps its address.
      setInvoice(null);
      setStatus(null);
      setAsset(code);
      openInvoice(code);
      return;
    }
    setAsset(code);
  };

  // The countdown, once a second. It is driven off the server's `expires_at`,
  // which carries a UTC offset, so a laptop in another timezone still counts
  // down from the right instant.
  useEffect(() => {
    if (!invoice) return undefined;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [invoice]);

  // What the chain has done with the address.
  useEffect(() => {
    if (!invoice || paid) return undefined;

    let cancelled = false;
    let timer = null;

    const poll = async () => {
      try {
        const res = await axios.get(`${API}/payments/crypto/status/${orderId}`, {
          headers: authHeaders(),
          withCredentials: true,
        });
        if (cancelled) return;
        setStatus(res.data);
        if (res.data.payment_status === 'paid' || res.data.status === 'confirmed') {
          setPaid(true);
          return;
        }
      } catch (err) {
        if (cancelled) return;
        // A 404 here means the invoice is gone (or never belonged to this
        // customer), which no amount of retrying fixes. Anything else - a cold
        // start, a wallet that is briefly down - is worth another look.
        const httpStatus = err.response?.status;
        if (httpStatus === 401 || httpStatus === 403 || httpStatus === 404) {
          setError(err.response?.data?.detail || 'This invoice is no longer available.');
          return;
        }
      }
      timer = setTimeout(poll, POLL_INTERVAL_MS);
    };

    poll();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [invoice, paid, orderId, authHeaders]);

  const expiresAtMs = invoice ? new Date(invoice.expires_at).getTime() : 0;
  const secondsLeft = invoice ? Math.floor((expiresAtMs - now) / 1000) : 0;
  // The server owns expiry; this is only what the page shows between polls.
  const quoteOver = Boolean(
    invoice && !paid && (status?.status === 'expired' || secondsLeft <= 0)
  );

  // What is still missing, for the partial case. Display only: the server
  // compares atomic units, this line just stops "1 of 1 confirmations" next to
  // a short payment from reading like the order is settled.
  const shortfall = (() => {
    if (!invoice || !status || status.status !== 'partial') return '';
    const diff = Number(invoice.amount) - Number(status.received);
    if (!(diff > 0)) return '';
    return diff.toFixed(12).replace(/0+$/, '').replace(/\.$/, '');
  })();

  const copy = async (label, value) => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(label);
      toast.success(
        label === 'address' ? 'Address copied' : 'Payment request copied'
      );
      setTimeout(() => {
        if (mounted.current) setCopied('');
      }, 2000);
    } catch {
      toast.error('Your browser would not let the page copy. Select the text instead.');
    }
  };

  const assets = methods?.crypto?.assets || [];

  if (paid) {
    return (
      <div
        className="min-h-screen flex items-center justify-center p-6"
        data-testid="crypto-payment-page"
      >
        <Card className="w-full max-w-md">
          <CardContent className="p-8 text-center">
            <CheckCircle className="w-16 h-16 text-green-500 mx-auto mb-6" />
            <h1 className="text-2xl font-bold mb-2">Payment Confirmed</h1>
            <p className="text-muted-foreground mb-2">
              Your order is paid and the kitchen has been told.
            </p>
            {invoice && (
              <p className="text-lg font-mono font-bold text-primary mb-6">
                {invoice.amount} {invoice.unit} · {formatDollars(invoice.fiat_total_cents)}
              </p>
            )}
            <div className="flex flex-col gap-3">
              <Button onClick={() => navigate('/orders')} data-testid="view-orders-button">
                View My Orders
              </Button>
              <Button variant="outline" onClick={() => navigate(`/orders/${orderId}`)}>
                Track This Order
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div
      className="min-h-screen flex items-center justify-center p-6"
      data-testid="crypto-payment-page"
    >
      <Card className="w-full max-w-lg">
        <CardHeader className="pb-2">
          <div className="flex items-center justify-between">
            <Link
              to="/orders"
              className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
            >
              <ArrowLeft className="w-4 h-4" />
              Orders
            </Link>
            {methods?.crypto?.enabled && (
              <Badge variant="outline" data-testid="crypto-enabled-badge">
                Crypto
              </Badge>
            )}
          </div>
          <CardTitle className="text-xl">
            {invoice ? `Pay ${invoice.asset_name}` : 'Pay with crypto'}
          </CardTitle>
        </CardHeader>

        <CardContent className="space-y-5">
          {error && (
            <div
              className="flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800"
              data-testid="crypto-error"
            >
              <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" />
              <span>{error}</span>
            </div>
          )}

          {methods && !methods.crypto?.enabled && (
            <div className="text-sm text-muted-foreground space-y-3" data-testid="crypto-unavailable">
              <p>
                This server does not take crypto payments right now. Your order is
                saved and still payable.
              </p>
              <Button variant="outline" onClick={() => navigate('/orders')}>
                Back to orders
              </Button>
            </div>
          )}

          {assets.length > 0 && (
            <div className="space-y-2">
              <p className="text-sm text-muted-foreground">Choose a coin</p>
              <div className="flex flex-wrap gap-2">
                {assets.map((option) => (
                  <Button
                    key={option.code}
                    variant={option.code === asset ? 'default' : 'outline'}
                    size="sm"
                    // The address is the promise: changing coin means a new
                    // address, so it waits for the current quote to be done.
                    disabled={Boolean(invoice) && !quoteOver}
                    onClick={() => chooseAsset(option.code)}
                    data-testid={`crypto-asset-${option.code}`}
                  >
                    <AssetIcon code={option.code} />
                    <span className="ml-2">{option.name}</span>
                  </Button>
                ))}
              </div>
              {assets.length > 1 && !invoice && (
                <p className="text-xs text-muted-foreground">
                  Both send to a fresh address and both settle the same order.
                </p>
              )}
            </div>
          )}

          {starting && !invoice && (
            <div className="flex items-center gap-2 text-sm text-muted-foreground" data-testid="crypto-quoting">
              <Loader2 className="w-4 h-4 animate-spin" />
              Quoting your order and reserving an address…
            </div>
          )}

          {invoice && quoteOver && (
            <div className="space-y-3" data-testid="crypto-quote-expired">
              <div className="flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
                <Clock className="w-4 h-4 mt-0.5 shrink-0" />
                <span>
                  This quote expired, so the amount is no longer pinned to a price.
                  Nothing was charged. Money sent to that address is still watched
                  for a while — check this page again before paying a second time.
                </span>
              </div>
              <div className="flex flex-wrap gap-2">
                <Button
                  size="sm"
                  onClick={() => {
                    setInvoice(null);
                    setStatus(null);
                    openInvoice(asset);
                  }}
                  disabled={starting}
                  data-testid="crypto-new-quote"
                >
                  <RefreshCw className="w-4 h-4 mr-1" />
                  Get a fresh quote
                </Button>
                <Button variant="outline" size="sm" onClick={() => navigate('/orders')}>
                  Pay by card instead
                </Button>
              </div>
            </div>
          )}

          {invoice && !quoteOver && (
            <>
              <div className="flex items-center justify-between text-sm">
                <span className="text-muted-foreground">Send exactly</span>
                <span
                  className="font-mono font-bold text-lg"
                  data-testid="crypto-amount"
                >
                  {invoice.amount} {invoice.unit}
                </span>
              </div>

              <div className="flex items-center justify-center rounded-xl border border-border bg-white p-4">
                <div data-testid="crypto-qr">
                  <QRCodeSVG
                    value={invoice.uri}
                    size={208}
                    level="M"
                    includeMargin={false}
                    bgColor="#ffffff"
                    fgColor="#000000"
                  />
                </div>
              </div>

              <div className="space-y-2">
                <div className="flex items-center justify-between gap-2 rounded-lg bg-secondary/40 p-3">
                  <span
                    className="font-mono text-xs break-all"
                    data-testid="crypto-address"
                  >
                    {invoice.address}
                  </span>
                  <Button
                    variant="ghost"
                    size="icon"
                    onClick={() => copy('address', invoice.address)}
                    aria-label="Copy address"
                    data-testid="crypto-copy-address"
                  >
                    {copied === 'address' ? (
                      <Check className="w-4 h-4 text-green-600" />
                    ) : (
                      <Copy className="w-4 h-4" />
                    )}
                  </Button>
                </div>
                <div className="flex items-center justify-between text-xs text-muted-foreground">
                  <span>
                    {formatDollars(invoice.fiat_total_cents)} at{' '}
                    {formatDollars(invoice.rate_cents_per_coin)} / {invoice.unit}
                  </span>
                  <button
                    type="button"
                    className="underline hover:text-foreground"
                    onClick={() => copy('uri', invoice.uri)}
                    data-testid="crypto-copy-uri"
                  >
                    Copy payment request
                  </button>
                </div>
              </div>

              <div className="rounded-lg border border-border p-3 space-y-2">
                <div className="flex items-center justify-between text-sm">
                  <span className="inline-flex items-center gap-2">
                    <Clock className="w-4 h-4 text-muted-foreground" />
                    <span data-testid="crypto-countdown" className="font-mono">
                      {formatClock(secondsLeft)} left
                    </span>
                  </span>
                  <Badge variant="secondary" data-testid="crypto-status">
                    {status?.status === 'partial' ? 'Payment seen' : 'Waiting'}
                  </Badge>
                </div>

                <p className="text-xs text-muted-foreground" data-testid="crypto-progress">
                  Received{' '}
                  <span className="font-mono text-foreground">
                    {status?.received ?? '0'} {invoice.unit}
                  </span>{' '}
                  of {invoice.amount} {invoice.unit}
                  {status
                    ? ` · ${status.confirmations} of ${status.confirmations_required} confirmations`
                    : ''}
                </p>

                {shortfall && (
                  <p
                    className="text-xs text-amber-700"
                    data-testid="crypto-shortfall"
                  >
                    Still short {shortfall} {invoice.unit}. Send the remainder to
                    the same address; both transactions count.
                  </p>
                )}

                {status && !status.wallet_ok && (
                  <p className="text-xs text-amber-700">
                    The server&apos;s wallet is not answering this minute. Your
                    payment is still on the chain and the countdown still applies.
                  </p>
                )}
              </div>

              <p className="text-xs text-muted-foreground">
                Send the full amount; anything short is watched but does not settle
                the order. The network fee is yours, not the restaurant's.
              </p>
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
};

export default CryptoPayment;
