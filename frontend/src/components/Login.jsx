import { useState } from 'react';
import { api } from '../api';
import './Login.css';

export default function Login({ onLoginSuccess }) {
    const [step, setStep] = useState('email'); // 'email' or 'otp'
    const [email, setEmail] = useState('');
    const [otp, setOtp] = useState('');
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');

    const handleRequestOTP = async (e) => {
        e.preventDefault();
        setError('');
        setLoading(true);

        try {
            await api.requestOTP(email);
            setStep('otp');
        } catch (err) {
            setError(err.message || 'Failed to send OTP');
        } finally {
            setLoading(false);
        }
    };

    const handleVerifyOTP = async (e) => {
        e.preventDefault();
        setError('');
        setLoading(false);

        try {
            const response = await api.verifyOTP(email, otp);
            // Store JWT and user info
            api.setJWT(response.token);
            localStorage.setItem('user_email', response.email);
            localStorage.setItem('user_id', response.user_id);
            onLoginSuccess(response);
        } catch (err) {
            setError(err.message || 'Invalid OTP');
        } finally {
            setLoading(false);
        }
    };

    const handleBackToEmail = () => {
        setStep('email');
        setOtp('');
        setError('');
    };

    return (
        <div className="login-container">
            <div className="login-card">
                <div className="login-header">
                    <h1>🏛️ LLM Council</h1>
                    <p>Sign in to continue</p>
                </div>

                {step === 'email' ? (
                    <form onSubmit={handleRequestOTP} className="login-form">
                        <div className="form-group">
                            <label htmlFor="email">Email Address</label>
                            <input
                                id="email"
                                type="email"
                                value={email}
                                onChange={(e) => setEmail(e.target.value)}
                                placeholder="you@example.com"
                                required
                                autoFocus
                                disabled={loading}
                            />
                        </div>

                        {error && <div className="error-message">{error}</div>}

                        <button type="submit" className="login-button" disabled={loading}>
                            {loading ? 'Sending...' : 'Send Login Code'}
                        </button>

                        <p className="login-hint">
                            We'll send a 6-digit code to your email
                        </p>
                    </form>
                ) : (
                    <form onSubmit={handleVerifyOTP} className="login-form">
                        <div className="form-group">
                            <label htmlFor="otp">Enter 6-Digit Code</label>
                            <input
                                id="otp"
                                type="text"
                                value={otp}
                                onChange={(e) => setOtp(e.target.value.replace(/\D/g, '').slice(0, 6))}
                                placeholder="000000"
                                required
                                autoFocus
                                disabled={loading}
                                className="otp-input"
                                maxLength={6}
                            />
                        </div>

                        <p className="login-hint">
                            Code sent to <strong>{email}</strong>
                        </p>

                        {error && <div className="error-message">{error}</div>}

                        <button type="submit" className="login-button" disabled={loading || otp.length !== 6}>
                            {loading ? 'Verifying...' : 'Verify & Login'}
                        </button>

                        <button
                            type="button"
                            onClick={handleBackToEmail}
                            className="back-button"
                            disabled={loading}
                        >
                            ← Use different email
                        </button>
                    </form>
                )}
            </div>
        </div>
    );
}
