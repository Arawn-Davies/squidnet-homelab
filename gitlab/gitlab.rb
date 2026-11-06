## SQUIDNET git server (git container) - GitLab CE behind NPM (PROXY_IP). 2026-11-06
external_url 'https://git.lab.example.co.uk'
# NPM terminates TLS; GitLab serves plain HTTP on :80 (CT firewall: :80 from PROXY_IP only)
nginx['listen_port'] = 80
nginx['listen_https'] = false
nginx['real_ip_trusted_addresses'] = ['PROXY_IP']
nginx['real_ip_header'] = 'X-Forwarded-For'
nginx['real_ip_recursive'] = 'on'
gitlab_rails['trusted_proxies'] = ['PROXY_IP']
letsencrypt['enable'] = false
# git over SSH goes straight to the container (git.lab.example.co.uk resolves to the proxy)
gitlab_rails['gitlab_ssh_host'] = 'git-ssh.lan'
gitlab_rails['time_zone'] = 'Europe/London'
# unprivileged LXC: Omnibus must not run 'sysctl --system'
package['modify_kernel_parameters'] = false
# single-user sizing (GitLab "memory-constrained environments" guidance)
puma['worker_processes'] = 0
sidekiq['concurrency'] = 10
prometheus_monitoring['enable'] = false
gitlab_rails['env'] = { 'MALLOC_CONF' => 'dirty_decay_ms:1000,muzzy_decay_ms:1000' }
gitaly['env'] = { 'MALLOC_CONF' => 'dirty_decay_ms:1000,muzzy_decay_ms:1000' }
# no product usage data
gitlab_rails['initial_gitlab_product_usage_data'] = false
# backups: gitlab-backup -> /var/opt/gitlab/backups, keep 7 days
gitlab_rails['backup_keep_time'] = 604800

## SSO (Authentik, app "GitLab", bound to akadmin). Secret lives in /etc/gitlab/authentik_client_secret (root 600).
gitlab_rails['omniauth_enabled'] = true
gitlab_rails['omniauth_allow_single_sign_on'] = ['openid_connect']
gitlab_rails['omniauth_block_auto_created_users'] = false
gitlab_rails['omniauth_auto_link_user'] = ['openid_connect']
gitlab_rails['omniauth_providers'] = [
  {
    name: "openid_connect",
    label: "Authentik",
    args: {
      name: "openid_connect",
      scope: ["openid", "profile", "email"],
      response_type: "code",
      issuer: "https://auth.lab.example.co.uk/application/o/gitlab/",
      discovery: true,
      client_auth_method: "query",
      uid_field: "preferred_username",
      send_scope_to_token_endpoint: "true",
      pkce: true,
      client_options: {
        identifier: "gitlab",
        secret: File.read('/etc/gitlab/authentik_client_secret').strip,
        redirect_uri: "https://git.lab.example.co.uk/users/auth/openid_connect/callback"
      }
    }
  }
]
