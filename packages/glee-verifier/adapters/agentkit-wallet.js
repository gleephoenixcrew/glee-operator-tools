/**
 * Optional structural adapter. Importing it never imports or installs AgentKit.
 * The caller supplies an existing wallet provider and keeps signing authority.
 */
export function asGleeWallet(provider) {
  for (const name of ["getNetwork", "getAddress", "signTypedData"]) {
    if (typeof provider?.[name] !== "function") {
      throw new TypeError(`AgentKit wallet adapter requires ${name}()`);
    }
  }
  return Object.freeze({
    async getChainId() {
      const network = await provider.getNetwork();
      if (network?.protocolFamily !== "evm") {
        throw new Error("AgentKit wallet must report an EVM network");
      }
      const value = network.chainId;
      if (
        !((typeof value === "string" && /^[1-9][0-9]*$/.test(value)) ||
          (typeof value === "number" && Number.isSafeInteger(value) && value > 0))
      ) {
        throw new Error("AgentKit wallet must report an explicit numeric chainId");
      }
      const chainId = Number(value);
      if (!Number.isSafeInteger(chainId)) throw new Error("Wallet chainId is out of range");
      return chainId;
    },
    getAddress() {
      return provider.getAddress();
    },
    signTypedData(data) {
      return provider.signTypedData(data);
    },
  });
}
