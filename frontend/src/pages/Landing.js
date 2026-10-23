import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion } from 'framer-motion';
import { useAuth } from '../contexts/AuthContext';
import { useTheme } from '../contexts/ThemeContext';
import { Button } from '../components/ui/button';
import { 
  UtensilsCrossed, Truck, Store, Building2, Users, 
  ArrowRight, Heart, MapPin, Shield, Sun, Moon,
  ChevronRight
} from 'lucide-react';

const Landing = () => {
  const navigate = useNavigate();
  const { isAuthenticated } = useAuth();
  const { theme, toggleTheme } = useTheme();
  const [stats, setStats] = useState({
    meals: 12847,
    saved: 3291,
    drivers: 156
  });

  useEffect(() => {
    if (isAuthenticated) {
      navigate('/dashboard');
    }
  }, [isAuthenticated, navigate]);

  // Animate stats
  useEffect(() => {
    const interval = setInterval(() => {
      setStats(prev => ({
        meals: prev.meals + Math.floor(Math.random() * 3),
        saved: prev.saved + (Math.random() > 0.7 ? 1 : 0),
        drivers: prev.drivers
      }));
    }, 5000);
    return () => clearInterval(interval);
  }, []);

  const roles = [
    {
      id: 'customer',
      icon: UtensilsCrossed,
      title: 'Order Food',
      description: 'Discover local restaurants and get fresh meals delivered to your door.',
      color: 'from-green-500/20 to-green-600/10',
      iconColor: 'text-green-600 dark:text-green-400'
    },
    {
      id: 'driver',
      icon: Truck,
      title: 'Deliver',
      description: 'Join our driver network. Flexible hours, fair pay, community impact.',
      color: 'from-blue-500/20 to-blue-600/10',
      iconColor: 'text-blue-600 dark:text-blue-400'
    },
    {
      id: 'restaurant',
      icon: Store,
      title: 'Partner Restaurant',
      description: 'Reach more customers. Reduce waste. Make a difference.',
      color: 'from-orange-500/20 to-orange-600/10',
      iconColor: 'text-orange-600 dark:text-orange-400'
    },
    {
      id: 'organization',
      icon: Building2,
      title: 'Organization',
      description: 'Register your food bank or shelter to receive surplus food.',
      color: 'from-purple-500/20 to-purple-600/10',
      iconColor: 'text-purple-600 dark:text-purple-400'
    }
  ];

  const handleRoleSelect = (roleId) => {
    navigate(`/auth?role=${roleId}`);
  };

  return (
    <div className="min-h-screen bg-background">
      {/* Header */}
      <header className="fixed top-0 left-0 right-0 z-50 glass-card border-b border-border/50">
        <div className="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-primary flex items-center justify-center">
              <span className="text-xl font-bold text-primary-foreground">S</span>
            </div>
            <span className="text-xl font-bold tracking-tight">SharePlate</span>
          </div>
          
          <div className="flex items-center gap-4">
            <button
              onClick={toggleTheme}
              className="p-2 rounded-lg hover:bg-secondary transition-colors"
              data-testid="landing-theme-toggle"
            >
              {theme === 'dark' ? <Sun className="w-5 h-5" /> : <Moon className="w-5 h-5" />}
            </button>
            <Button
              variant="ghost"
              onClick={() => navigate('/auth')}
              data-testid="login-button"
            >
              Sign In
            </Button>
            <Button
              onClick={() => navigate('/auth?mode=register')}
              className="btn-pill hidden sm:flex"
              data-testid="get-started-button"
            >
              Get Started
              <ArrowRight className="w-4 h-4 ml-2" />
            </Button>
          </div>
        </div>
      </header>

      {/* Hero Section */}
      <section className="hero-bg pt-32 pb-20 md:pt-40 md:pb-32">
        <div className="max-w-7xl mx-auto px-6">
          <div className="grid md:grid-cols-2 gap-12 items-center">
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.6 }}
            >
              <h1 className="text-5xl md:text-7xl font-extrabold tracking-tight leading-tight">
                Feed the<br />
                <span className="text-gradient">Community</span>,<br />
                Fuel the Drive
              </h1>
              <p className="mt-6 text-lg md:text-xl text-muted-foreground max-w-lg">
                A food delivery platform that connects restaurants, drivers, and communities 
                to reduce waste and ensure no one goes hungry.
              </p>
              <div className="mt-8 flex flex-wrap gap-4">
                <Button
                  size="lg"
                  className="btn-pill bg-primary hover:bg-primary/90"
                  onClick={() => navigate('/auth?mode=register')}
                  data-testid="hero-cta-button"
                >
                  Start Ordering
                  <ChevronRight className="w-5 h-5 ml-1" />
                </Button>
                <Button
                  size="lg"
                  variant="outline"
                  className="btn-pill"
                  onClick={() => navigate('/auth?role=driver')}
                >
                  Become a Driver
                </Button>
              </div>
            </motion.div>

            {/* Hero Image */}
            <motion.div
              initial={{ opacity: 0, scale: 0.95 }}
              animate={{ opacity: 1, scale: 1 }}
              transition={{ duration: 0.6, delay: 0.2 }}
              className="relative"
            >
              <div className="aspect-square rounded-3xl overflow-hidden shadow-2xl">
                <img
                  src="https://images.unsplash.com/photo-1740597105341-c799b37f6703?w=800&q=80"
                  alt="Community food sharing"
                  className="w-full h-full object-cover"
                />
              </div>
              {/* Floating Stats Card */}
              <motion.div
                initial={{ opacity: 0, x: 20 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ duration: 0.6, delay: 0.4 }}
                className="absolute -bottom-6 -left-6 glass-card p-6 shadow-xl"
              >
                <div className="flex items-center gap-4">
                  <div className="w-12 h-12 rounded-full bg-green-500/20 flex items-center justify-center">
                    <Heart className="w-6 h-6 text-green-600" />
                  </div>
                  <div>
                    <p className="text-3xl font-bold font-mono text-primary">
                      {stats.saved.toLocaleString()}
                    </p>
                    <p className="text-sm text-muted-foreground">Meals Saved Today</p>
                  </div>
                </div>
              </motion.div>
            </motion.div>
          </div>
        </div>
      </section>

      {/* Role Selection */}
      <section className="py-20 md:py-32">
        <div className="max-w-7xl mx-auto px-6">
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
            className="text-center mb-16"
          >
            <h2 className="text-4xl md:text-5xl font-bold tracking-tight">
              How Will You <span className="text-gradient">Contribute</span>?
            </h2>
            <p className="mt-4 text-lg text-muted-foreground max-w-2xl mx-auto">
              Whether you're hungry, driving, cooking, or helping—there's a place for you.
            </p>
          </motion.div>

          <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-6">
            {roles.map((role, index) => (
              <motion.div
                key={role.id}
                initial={{ opacity: 0, y: 20 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true }}
                transition={{ delay: index * 0.1 }}
                className={`role-card bg-gradient-to-br ${role.color}`}
                onClick={() => handleRoleSelect(role.id)}
                data-testid={`role-card-${role.id}`}
              >
                <div className={`w-14 h-14 rounded-2xl bg-background/80 flex items-center justify-center mb-6 ${role.iconColor}`}>
                  <role.icon className="w-7 h-7" />
                </div>
                <h3 className="text-xl font-bold mb-2">{role.title}</h3>
                <p className="text-muted-foreground text-sm">{role.description}</p>
                <div className="mt-6 flex items-center text-primary font-semibold">
                  Get Started
                  <ArrowRight className="w-4 h-4 ml-2" />
                </div>
              </motion.div>
            ))}
          </div>
        </div>
      </section>

      {/* Impact Stats */}
      <section className="py-20 bg-secondary/30">
        <div className="max-w-7xl mx-auto px-6">
          <div className="grid md:grid-cols-3 gap-8">
            <motion.div
              initial={{ opacity: 0, scale: 0.95 }}
              whileInView={{ opacity: 1, scale: 1 }}
              viewport={{ once: true }}
              className="impact-counter"
            >
              <span className="impact-number">{stats.meals.toLocaleString()}</span>
              <span className="impact-label">Meals Delivered</span>
            </motion.div>
            <motion.div
              initial={{ opacity: 0, scale: 0.95 }}
              whileInView={{ opacity: 1, scale: 1 }}
              viewport={{ once: true }}
              transition={{ delay: 0.1 }}
              className="impact-counter"
            >
              <span className="impact-number">{stats.saved.toLocaleString()}</span>
              <span className="impact-label">Surplus Meals Saved</span>
            </motion.div>
            <motion.div
              initial={{ opacity: 0, scale: 0.95 }}
              whileInView={{ opacity: 1, scale: 1 }}
              viewport={{ once: true }}
              transition={{ delay: 0.2 }}
              className="impact-counter"
            >
              <span className="impact-number">{stats.drivers}</span>
              <span className="impact-label">Active Drivers</span>
            </motion.div>
          </div>
        </div>
      </section>

      {/* Features */}
      <section className="py-20 md:py-32">
        <div className="max-w-7xl mx-auto px-6">
          <div className="grid md:grid-cols-3 gap-8">
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true }}
              className="marketing-card"
            >
              <MapPin className="w-10 h-10 text-primary mb-4" />
              <h3 className="text-xl font-bold mb-2">Smart Routing</h3>
              <p className="text-muted-foreground">
                Our algorithm optimizes delivery routes to include food distribution 
                stops without adding significant distance.
              </p>
            </motion.div>
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true }}
              transition={{ delay: 0.1 }}
              className="marketing-card"
            >
              <Shield className="w-10 h-10 text-primary mb-4" />
              <h3 className="text-xl font-bold mb-2">End-to-End Encryption</h3>
              <p className="text-muted-foreground">
                Your location and payment data are encrypted using AES-256, 
                ensuring your privacy is always protected.
              </p>
            </motion.div>
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true }}
              transition={{ delay: 0.2 }}
              className="marketing-card"
            >
              <Users className="w-10 h-10 text-primary mb-4" />
              <h3 className="text-xl font-bold mb-2">Community Support</h3>
              <p className="text-muted-foreground">
                Drivers and customers can answer support questions, 
                building a helpful community that understands real issues.
              </p>
            </motion.div>
          </div>
        </div>
      </section>

      {/* CTA Section */}
      <section className="py-20 md:py-32 bg-primary/5">
        <div className="max-w-4xl mx-auto px-6 text-center">
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
          >
            <h2 className="text-4xl md:text-5xl font-bold tracking-tight mb-6">
              Ready to Make a Difference?
            </h2>
            <p className="text-lg text-muted-foreground mb-8 max-w-2xl mx-auto">
              Join thousands of users who are changing how food reaches communities. 
              Every order, every delivery, every donation matters.
            </p>
            <Button
              size="lg"
              className="btn-pill bg-primary hover:bg-primary/90"
              onClick={() => navigate('/auth?mode=register')}
              data-testid="footer-cta-button"
            >
              Join SharePlate Today
              <ArrowRight className="w-5 h-5 ml-2" />
            </Button>
          </motion.div>
        </div>
      </section>

      {/* Footer */}
      <footer className="py-12 border-t border-border">
        <div className="max-w-7xl mx-auto px-6">
          <div className="flex flex-col md:flex-row items-center justify-between gap-4">
            <div className="flex items-center gap-3">
              <div className="w-8 h-8 rounded-lg bg-primary flex items-center justify-center">
                <span className="text-sm font-bold text-primary-foreground">S</span>
              </div>
              <span className="font-bold">SharePlate</span>
            </div>
            <p className="text-sm text-muted-foreground">
              Building a world where no food goes to waste.
            </p>
          </div>
        </div>
      </footer>
    </div>
  );
};

export default Landing;
