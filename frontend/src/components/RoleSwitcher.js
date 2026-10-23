import React, { useState } from 'react';
import { useAuth } from '../contexts/AuthContext';
import { Button } from './ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from './ui/dropdown-menu';
import { toast } from 'sonner';
import { 
  User, Truck, Store, Building2, Shield, ChevronDown, Check
} from 'lucide-react';

const roles = [
  { id: 'customer', label: 'Customer', icon: User, description: 'Order food' },
  { id: 'driver', label: 'Driver', icon: Truck, description: 'Deliver orders' },
  { id: 'restaurant', label: 'Restaurant', icon: Store, description: 'Manage menu' },
  { id: 'organization', label: 'Organization', icon: Building2, description: 'Receive donations' },
  { id: 'admin', label: 'Admin', icon: Shield, description: 'Manage platform' },
];

const RoleSwitcher = ({ compact = false }) => {
  const { user, updateProfile } = useAuth();
  const [switching, setSwitching] = useState(false);
  
  const currentRole = roles.find(r => r.id === user?.role) || roles[0];
  const CurrentIcon = currentRole.icon;

  const handleRoleSwitch = async (roleId) => {
    if (roleId === user?.role) return;
    
    setSwitching(true);
    try {
      await updateProfile({ role: roleId });
      toast.success(`Switched to ${roles.find(r => r.id === roleId)?.label} view`);
      // Reload to update sidebar navigation
      window.location.href = '/dashboard';
    } catch (error) {
      toast.error('Failed to switch role');
    } finally {
      setSwitching(false);
    }
  };

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button 
          variant="outline" 
          className={compact ? "w-full justify-between" : "gap-2"}
          disabled={switching}
          data-testid="role-switcher"
        >
          <div className="flex items-center gap-2">
            <CurrentIcon className="w-4 h-4" />
            {!compact && <span>{currentRole.label}</span>}
            {compact && <span className="flex-1 text-left">{currentRole.label}</span>}
          </div>
          <ChevronDown className="w-4 h-4 opacity-50" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-56">
        <DropdownMenuLabel>Switch Dashboard View</DropdownMenuLabel>
        <DropdownMenuSeparator />
        {roles.map((role) => {
          const Icon = role.icon;
          const isActive = role.id === user?.role;
          
          return (
            <DropdownMenuItem
              key={role.id}
              onClick={() => handleRoleSwitch(role.id)}
              className="flex items-center gap-3 cursor-pointer"
              data-testid={`switch-to-${role.id}`}
            >
              <Icon className={`w-4 h-4 ${isActive ? 'text-primary' : ''}`} />
              <div className="flex-1">
                <p className={`font-medium ${isActive ? 'text-primary' : ''}`}>
                  {role.label}
                </p>
                <p className="text-xs text-muted-foreground">{role.description}</p>
              </div>
              {isActive && <Check className="w-4 h-4 text-primary" />}
            </DropdownMenuItem>
          );
        })}
      </DropdownMenuContent>
    </DropdownMenu>
  );
};

export default RoleSwitcher;
