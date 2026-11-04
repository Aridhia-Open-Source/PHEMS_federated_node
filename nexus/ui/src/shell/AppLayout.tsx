import { useState } from "react";
import { Link, Outlet, useLocation } from "react-router-dom";

import { AppHeader, AppShell, Button, Icon, NavList, SideMenu, SideMenuDivider } from "@/ui";
import { setToken } from "@/api/auth";
import { queryClient } from "@/api/queryClient";

import { Logo } from "./Logo";
import { shellMessages } from "./messages";
import { activeNavId, navGroups } from "./nav";
import { renderLink } from "./RouterLink";
import { ThemeToggle } from "./ThemeToggle";

/** Header, menu panel and content area for every page after login. */
export function AppLayout() {
  const pathname = useLocation().pathname;
  const [menuOpen, setMenuOpen] = useState(false);
  const closeMenu = () => setMenuOpen(false);
  const logOut = () => {
    closeMenu();
    setToken(null);
    queryClient.clear();
  };

  return (
    <AppShell
      header={
        <AppHeader
          logo={
            <Link to="/projects" className="no-underline">
              <Logo />
            </Link>
          }
          tools={<ThemeToggle onBlue />}
          menuOpen={menuOpen}
          onMenuClick={() => setMenuOpen(true)}
        />
      }
    >
      <SideMenu
        open={menuOpen}
        onOpenChange={setMenuOpen}
        title={shellMessages.menuTitle}
        description={shellMessages.menuDescription}
      >
        {navGroups.map((group) => (
          <NavList
            key={group.label}
            label={group.label}
            items={group.items}
            activeId={activeNavId(pathname)}
            renderLink={renderLink}
            onNavigate={closeMenu}
          />
        ))}
        <SideMenuDivider />
        <Button type="button" size="lg" onBlue className="self-start" onClick={logOut}>
          {shellMessages.logOut}
          <Icon name="logOut" size="xl" />
        </Button>
      </SideMenu>
      {/* Pages not yet restyled still rely on the rules in style.css, scoped to this wrapper. */}
      <div className="legacy">
        <Outlet />
      </div>
    </AppShell>
  );
}
