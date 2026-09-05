import { LitElement, html } from "lit"
import { customElement, state } from "lit/decorators.js"

import { api, type Person } from "../data"

/**
 * Sign in — the canvas's A2.3 dialog, made to work.
 *
 * The drawing shows three provider buttons and explains that signing in is
 * not the same as connecting GitHub. Real OAuth is the backend's (week 2), so
 * tonight each provider button signs in the seeded Member; below them the
 * demo accounts are listed plainly so the room can switch role in one click.
 * Nothing pretends to be a real sign-in: the dialog says which it is.
 */
@customElement("dn-role-switch")
export class DnRoleSwitch extends LitElement {
  @state() private accounts: Person[] = []

  protected createRenderRoot() {
    return this
  }

  async connectedCallback() {
    super.connectedCallback()
    this.accounts = await api.accounts()
  }

  private get dialog() {
    return this.querySelector("dialog") as HTMLDialogElement | null
  }

  open() {
    this.dialog?.showModal()
  }
  close() {
    this.dialog?.close()
  }

  private async choose(handle: string) {
    const session = await api.signIn(handle)
    this.close()
    this.dispatchEvent(new CustomEvent("dn-signed-in", { detail: session, bubbles: true, composed: true }))
  }

  render() {
    const member = this.accounts.find((a) => a.role === "member")
    return html`
      <dialog class="dn-dialog" aria-labelledby="dn-signin-title" @cancel=${() => this.close()}>
        <div class="dialog-body">
          <div class="card-kicker">Sign in</div>
          <h2 class="dialog-title" id="dn-signin-title">Sign in to apply</h2>
          <p class="text-muted" style="margin-bottom:18px">
            Use the account you already have. Signing in is not the same as connecting
            GitHub — that is a separate, optional step, and you choose which repositories it can see.
          </p>

          <div class="dn-providers">
            ${["Google", "GitHub", "Facebook"].map(
              (p) => html`
                <button type="button" class="btn btn-secondary btn-block dn-provider" @click=${() => member && this.choose(member.handle)}>
                  Continue with ${p}
                </button>
              `
            )}
          </div>
          <p class="text-muted" style="font-size:12px;margin:10px 0 0">
            By continuing you accept the terms and the privacy notice. Provider sign-in is a demo tonight — each
            button signs in the sample member below.
          </p>

          <div class="hr" style="margin:18px 0 14px"></div>
          <div class="card-kicker" style="margin-bottom:8px">Demo accounts · switch role</div>
          <div class="dn-accounts">
            ${this.accounts.map(
              (a) => html`
                <button type="button" class="dn-account" @click=${() => this.choose(a.handle)}>
                  <span class="dn-avatar" aria-hidden="true">${a.initials}</span>
                  <span class="dn-person-text">
                    <span class="dn-person-name">${a.name} <span class="text-muted" lang="ne">· ${a.nameNe}</span></span>
                    <span class="dn-person-role">${a.roleLabel}</span>
                  </span>
                </button>
              `
            )}
          </div>
        </div>
        <div class="dialog-actions">
          <button type="button" class="btn btn-ghost" @click=${() => this.close()}>Not now</button>
        </div>
      </dialog>
    `
  }
}

declare global {
  interface HTMLElementTagNameMap {
    "dn-role-switch": DnRoleSwitch
  }
}
