import React, { useEffect, useRef, useState } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { Card, CardContent } from '../components/ui/card';
import { Button } from '../components/ui/button';
import axios from 'axios';
import { CheckCircle, XCircle, Loader2 } from 'lucide-react';

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

// The status endpoint asks Stripe, so the first poll after the redirect is
// usually enough. The rest of the budget covers Stripe's webhook and the
// browser arriving before the provider has finished settling the session.
const MAX_ATTEMPTS = 10;
const POLL_INTERVAL_MS = 2000;

const PaymentSuccess = () => {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const { token } = useAuth();
  const [status, setStatus] = useState('checking'); // checking, success, failed
  const [paymentData, setPaymentData] = useState(null);
  // Setting state after the customer has navigated away is a React warning at
  // best; this also stops the timer chain when the page unmounts.
  const cancelled = useRef(false);

  useEffect(() => {
    cancelled.current = false;
    const sessionId = searchParams.get('session_id');
    if (sessionId) {
      pollPaymentStatus(sessionId);
    } else {
      setStatus('failed');
    }
    return () => {
      cancelled.current = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const pollPaymentStatus = async (sessionId, attempts = 0) => {
    if (cancelled.current) return;

    if (attempts >= MAX_ATTEMPTS) {
      setStatus('failed');
      return;
    }

    try {
      const res = await axios.get(`${API}/payments/status/${sessionId}`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        withCredentials: true
      });
      if (cancelled.current) return;

      setPaymentData(res.data);

      if (res.data.payment_status === 'paid') {
        setStatus('success');
        return;
      }
      if (res.data.status === 'expired' || res.data.payment_status === 'failed') {
        setStatus('failed');
        return;
      }

      setTimeout(() => pollPaymentStatus(sessionId, attempts + 1), POLL_INTERVAL_MS);
    } catch (error) {
      if (cancelled.current) return;

      // A provider outage, a cold start, or a webhook that has not written the
      // payment row yet are all worth another request. Only a caller who is not
      // allowed to read this session will never improve by retrying.
      const httpStatus = error?.response?.status;
      if (httpStatus === 401 || httpStatus === 403) {
        setStatus('failed');
        return;
      }
      setTimeout(() => pollPaymentStatus(sessionId, attempts + 1), POLL_INTERVAL_MS);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center p-6" data-testid="payment-success-page">
      <Card className="w-full max-w-md">
        <CardContent className="p-8 text-center">
          {status === 'checking' && (
            <>
              <Loader2 className="w-16 h-16 animate-spin text-primary mx-auto mb-6" />
              <h1 className="text-2xl font-bold mb-2">Processing Payment</h1>
              <p className="text-muted-foreground">Please wait while we confirm your payment...</p>
            </>
          )}

          {status === 'success' && (
            <>
              <CheckCircle className="w-16 h-16 text-green-500 mx-auto mb-6" />
              <h1 className="text-2xl font-bold mb-2">Payment Successful!</h1>
              <p className="text-muted-foreground mb-6">
                Thank you for your order. We&apos;re letting the restaurant know.
              </p>
              {paymentData && (
                <p className="text-lg font-mono font-bold text-primary mb-6">
                  ${(paymentData.amount_total / 100).toFixed(2)} {paymentData.currency?.toUpperCase()}
                </p>
              )}
              <div className="flex flex-col gap-3">
                <Button onClick={() => navigate('/orders')} data-testid="view-orders-button">
                  View My Orders
                </Button>
                <Button variant="outline" onClick={() => navigate('/restaurants')}>
                  Order More Food
                </Button>
              </div>
            </>
          )}

          {status === 'failed' && (
            <>
              <XCircle className="w-16 h-16 text-red-500 mx-auto mb-6" />
              <h1 className="text-2xl font-bold mb-2">Payment Not Confirmed</h1>
              <p className="text-muted-foreground mb-6">
                We couldn&apos;t confirm a payment for this order. If you were charged,
                it will appear here once Stripe tells us — check your orders before
                paying again.
              </p>
              <div className="flex flex-col gap-3">
                <Button onClick={() => navigate('/orders')} data-testid="view-orders-button">
                  View My Orders
                </Button>
                <Button variant="outline" onClick={() => navigate('/restaurants')}>
                  Back to Restaurants
                </Button>
                <Button variant="outline" onClick={() => navigate('/support')}>
                  Get Help
                </Button>
              </div>
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
};

const PaymentCancel = () => {
  const navigate = useNavigate();

  return (
    <div className="min-h-screen flex items-center justify-center p-6" data-testid="payment-cancel-page">
      <Card className="w-full max-w-md">
        <CardContent className="p-8 text-center">
          <XCircle className="w-16 h-16 text-amber-500 mx-auto mb-6" />
          <h1 className="text-2xl font-bold mb-2">Payment Cancelled</h1>
          <p className="text-muted-foreground mb-6">
            No charge was made. Your order is still saved and unpaid — you can
            pay for it from your orders page.
          </p>
          <div className="flex flex-col gap-3">
            <Button onClick={() => navigate('/orders')}>
              View My Orders
            </Button>
            <Button variant="outline" onClick={() => navigate('/restaurants')}>
              Continue Shopping
            </Button>
            <Button variant="outline" onClick={() => navigate('/dashboard')}>
              Go to Dashboard
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
};

export { PaymentSuccess, PaymentCancel };
