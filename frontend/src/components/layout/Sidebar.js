import React, { useState } from 'react';
import { NavLink, useNavigate } from 'react-router-dom';
import { useAuth } from '../../contexts/AuthContext';
import { useTheme } from '../../contexts/ThemeContext';
import { Button } from '../ui/button';
import RoleSwitcher from '../../components/RoleSwitcher';
import { 
  Home, Store, ShoppingBag, Truck, Building2, Users, 
  HelpCircle, Settings, LogOut, Menu, X, Sun, Moon,
  BarChart3, MapPin, Heart
} from 'lucide-react';

const Sidebar = ({ mobile = false, onClose }) => {
  const { user, logout } = useAuth();
  const { theme, toggleTheme } = useTheme();
  const navigate = useNavigate();

  const handleLogout = async () => {
    await logout();
    navigate('/');
  };

  const getNavItems = () => {
    const role = user?.role || 'customer';
    
    const baseItems = [
      { to: '/dashboard', icon: Home, label: 'Dashboard' }
    ];

    const roleItems = {
      customer: [
        { to: '/restaurants', icon: Store, label: 'Restaurants' },
        { to: '/orders', icon: ShoppingBag, label: 'My Orders' },
        { to: '/donate', icon: Heart, label: 'Donate Food' }
      ],
      driver: [
        { to: '/driver/deliveries', icon: Truck, label: 'Deliveries' },
        { to: '/driver/earnings', icon: BarChart3, label: 'Earnings' },
        { to: '/driver/routing', icon: MapPin, label: 'Routing' }
      ],
      restaurant: [
        { to: '/restaurant/register', icon: Store, label: 'Register' },
        { to: '/restaurant/menu', icon: Store, label: 'Menu' },
        { to: '/restaurant/orders', icon: ShoppingBag, label: 'Orders' },
        { to: '/restaurant/surplus', icon: Heart, label: 'Surplus Food' }
      ],
      organization: [
        { to: '/organization/register', icon: Building2, label: 'Register Org' },
        { to: '/organization/requests', icon: Heart, label: 'Food Requests' },
        { to: '/organization/received', icon: ShoppingBag, label: 'Received' }
      ],
      admin: [
        { to: '/admin/analytics', icon: BarChart3, label: 'Analytics' },
        { to: '/admin/users', icon: Users, label: 'Users' },
        { to: '/admin/routing', icon: MapPin, label: 'Routing' }
      ]
    };

    return [
      ...baseItems,
      ...(roleItems[role] || roleItems.customer),
      { to: '/impact', icon: Heart, label: 'Community Impact' },
      { to: '/support', icon: HelpCircle, label: 'Community Support' },
      { to: '/settings', icon: Settings, label: 'Settings' }
    ];
  };

  const navItems = getNavItems();

  const sidebarContent = (
    <div className="flex flex-col h-full">
      {/* Logo */}
      <div className="p-6 border-b border-border">
        <NavLink to="/" className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-primary flex items-center justify-center">
            <span className="text-xl font-bold text-primary-foreground">S</span>
          </div>
          <span className="text-xl font-bold tracking-tight">SharePlate</span>
        </NavLink>
      </div>

      {/* Navigation */}
      <nav className="flex-1 p-4 space-y-1 overflow-y-auto">
        {navItems.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            onClick={onClose}
            className={({ isActive }) =>
              `sidebar-nav-item ${isActive ? 'active' : ''}`
            }
            data-testid={`nav-${item.label.toLowerCase().replace(' ', '-')}`}
          >
            <item.icon className="w-5 h-5" />
            <span>{item.label}</span>
          </NavLink>
        ))}
      </nav>

      {/* User Section */}
      <div className="p-4 border-t border-border space-y-4">
        {/* Role Switcher */}
        <div className="space-y-2">
          <p className="text-xs text-muted-foreground px-1">View as</p>
          <RoleSwitcher compact />
        </div>

        {/* Theme Toggle */}
        <button
          onClick={toggleTheme}
          className="sidebar-nav-item w-full"
          data-testid="theme-toggle"
        >
          {theme === 'dark' ? (
            <>
              <Sun className="w-5 h-5" />
              <span>Light Mode</span>
            </>
          ) : (
            <>
              <Moon className="w-5 h-5" />
              <span>Dark Mode</span>
            </>
          )}
        </button>

        {/* User Info */}
        {user && (
          <div className="p-3 rounded-xl bg-secondary/50">
            <div className="flex items-center gap-3">
              {user.picture ? (
                <img 
                  src={user.picture} 
                  alt={user.name} 
                  className="w-10 h-10 rounded-full"
                />
              ) : (
                <div className="w-10 h-10 rounded-full bg-primary/20 flex items-center justify-center">
                  <span className="text-primary font-semibold">
                    {user.name?.[0]?.toUpperCase() || 'U'}
                  </span>
                </div>
              )}
              <div className="flex-1 min-w-0">
                <p className="font-medium truncate">{user.name}</p>
                <p className="text-xs text-muted-foreground capitalize">{user.role}</p>
              </div>
            </div>
          </div>
        )}

        {/* Logout */}
        <Button
          variant="ghost"
          className="w-full justify-start gap-3 text-destructive hover:text-destructive hover:bg-destructive/10"
          onClick={handleLogout}
          data-testid="logout-button"
        >
          <LogOut className="w-5 h-5" />
          <span>Logout</span>
        </Button>
      </div>
    </div>
  );

  if (mobile) {
    return (
      <div className="glass-card h-full">
        <button
          onClick={onClose}
          className="absolute top-4 right-4 p-2 rounded-lg hover:bg-secondary"
        >
          <X className="w-5 h-5" />
        </button>
        {sidebarContent}
      </div>
    );
  }

  return (
    <aside className="hidden md:flex w-64 flex-col bg-card border-r border-border">
      {sidebarContent}
    </aside>
  );
};

export default Sidebar;
