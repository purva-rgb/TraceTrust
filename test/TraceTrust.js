const { expect } = require("chai");
const { ethers } = require("hardhat");
const { time } = require("@nomicfoundation/hardhat-network-helpers");

const Role = { NONE: 0, MANUFACTURER: 1, DISTRIBUTOR: 2, RETAILER: 3 };
const Lifecycle = { NONE: 0, REGISTERED: 1, IN_SUPPLY_CHAIN: 2, SOLD: 3 };
const TransferStatus = { NONE: 0, INITIATED: 1, ACCEPTED: 2, REJECTED: 3, CANCELLED: 4, EXPIRED: 5 };

const id = (label) => ethers.id(label);
const ZERO = ethers.ZeroHash;

async function deploy() {
  const [governance, manufacturer, distributor, retailer, outsider] = await ethers.getSigners();
  const factory = await ethers.getContractFactory("TraceTrust");
  const salt = id("deployment-salt-v1");
  const contract = await factory.deploy(salt);
  await contract.waitForDeployment();
  await contract.registerOrganization(manufacturer.address, Role.MANUFACTURER, true);
  await contract.registerOrganization(distributor.address, Role.DISTRIBUTOR, true);
  await contract.registerOrganization(retailer.address, Role.RETAILER, true);
  return { contract, governance, manufacturer, distributor, retailer, outsider, salt };
}

async function registerOne(contract, manufacturer, label = "laptop-1") {
  const productId = id(label);
  const eventHash = id(`${label}-genesis`);
  const operationUid = id(`${label}-register-op`);
  await contract.connect(manufacturer).registerProduct(productId, eventHash, operationUid);
  return { productId, eventHash, operationUid };
}

describe("TraceTrust", function () {
  it("registers a product for a manufacturer at seq 0", async function () {
    const { contract, manufacturer } = await deploy();
    const { productId, eventHash } = await registerOne(contract, manufacturer);
    const product = await contract.getProduct(productId);
    expect(product.custodian).to.equal(manufacturer.address);
    expect(product.seq).to.equal(0n);
    expect(product.eventHead).to.equal(eventHash);
    expect(product.lifecycle).to.equal(Lifecycle.REGISTERED);
  });

  it("rejects the wrong sender for registration", async function () {
    const { contract, distributor } = await deploy();
    await expect(
      contract.connect(distributor).registerProduct(id("p"), id("h"), id("op"))
    ).to.be.revertedWithCustomError(contract, "UnauthorizedRole");
  });

  it("rejects a duplicate product", async function () {
    const { contract, manufacturer } = await deploy();
    const { productId, eventHash } = await registerOne(contract, manufacturer, "dup");
    await expect(
      contract.connect(manufacturer).registerProduct(productId, eventHash, id("dup-op-2"))
    ).to.be.revertedWithCustomError(contract, "ProductExists");
  });

  it("rejects a replayed operationUid", async function () {
    const { contract, manufacturer } = await deploy();
    const op = id("replay-op");
    await contract.connect(manufacturer).registerProduct(id("p-a"), id("h-a"), op);
    await expect(
      contract.connect(manufacturer).registerProduct(id("p-b"), id("h-b"), op)
    ).to.be.revertedWithCustomError(contract, "DuplicateOperation");
  });

  it("moves manufacturer to distributor then distributor to retailer", async function () {
    const { contract, manufacturer, distributor, retailer } = await deploy();
    const { productId, eventHash } = await registerOne(contract, manufacturer, "flow");
    const transfer1 = id("t-m-d");
    const expiry = BigInt(await time.latest()) + 3600n;
    await contract.connect(manufacturer).initiateTransfer(
      transfer1,
      distributor.address,
      [productId],
      id("manifest-1"),
      expiry,
      [eventHash],
      [id("h-init-1")],
      id("op-init-1")
    );
    await contract.connect(distributor).acceptTransfer(
      transfer1,
      id("receipt-1"),
      [id("h-accept-1")],
      id("op-accept-1")
    );
    const afterDist = await contract.getProduct(productId);
    expect(afterDist.custodian).to.equal(distributor.address);
    expect(afterDist.lifecycle).to.equal(Lifecycle.IN_SUPPLY_CHAIN);
    expect(afterDist.reservedTransferId).to.equal(ZERO);

    const transfer2 = id("t-d-r");
    await contract.connect(distributor).initiateTransfer(
      transfer2,
      retailer.address,
      [productId],
      id("manifest-2"),
      expiry,
      [id("h-accept-1")],
      [id("h-init-2")],
      id("op-init-2")
    );
    await contract.connect(retailer).acceptTransfer(
      transfer2,
      id("receipt-2"),
      [id("h-accept-2")],
      id("op-accept-2")
    );
    const afterRetail = await contract.getProduct(productId);
    expect(afterRetail.custodian).to.equal(retailer.address);
    await contract.connect(retailer).recordSale(
      productId,
      id("h-accept-2"),
      id("h-sold"),
      id("op-sale")
    );
    const sold = await contract.getProduct(productId);
    expect(sold.lifecycle).to.equal(Lifecycle.SOLD);
    expect(sold.custodian).to.equal(retailer.address);
  });

  it("rejects the wrong recipient on accept", async function () {
    const { contract, manufacturer, distributor, retailer } = await deploy();
    const { productId, eventHash } = await registerOne(contract, manufacturer, "wrong-rcp");
    const transferId = id("t-wrong-rcp");
    const expiry = BigInt(await time.latest()) + 3600n;
    await contract.connect(manufacturer).initiateTransfer(
      transferId,
      distributor.address,
      [productId],
      id("m"),
      expiry,
      [eventHash],
      [id("h1")],
      id("op-i")
    );
    await expect(
      contract.connect(retailer).acceptTransfer(transferId, id("r"), [id("h2")], id("op-a"))
    ).to.be.revertedWithCustomError(contract, "NotRecipient");
  });

  it("rejects an illegal manufacturer-to-retailer edge", async function () {
    const { contract, manufacturer, retailer } = await deploy();
    const { productId, eventHash } = await registerOne(contract, manufacturer, "skip");
    const expiry = BigInt(await time.latest()) + 3600n;
    await expect(
      contract.connect(manufacturer).initiateTransfer(
        id("t-skip"),
        retailer.address,
        [productId],
        id("m"),
        expiry,
        [eventHash],
        [id("h1")],
        id("op-skip")
      )
    ).to.be.revertedWithCustomError(contract, "IllegalEdge");
  });

  it("rejects initiate when the sender is not the custodian", async function () {
    const { contract, manufacturer, distributor, retailer } = await deploy();
    const { productId, eventHash } = await registerOne(contract, manufacturer, "not-cust");
    const expiry = BigInt(await time.latest()) + 3600n;
    await expect(
      contract.connect(distributor).initiateTransfer(
        id("t-nc"),
        retailer.address,
        [productId],
        id("m"),
        expiry,
        [eventHash],
        [id("h1")],
        id("op-nc")
      )
    ).to.be.revertedWithCustomError(contract, "NotCustodian");
  });

  it("rejects a stale expected head", async function () {
    const { contract, manufacturer, distributor } = await deploy();
    const { productId } = await registerOne(contract, manufacturer, "stale");
    const expiry = BigInt(await time.latest()) + 3600n;
    await expect(
      contract.connect(manufacturer).initiateTransfer(
        id("t-stale"),
        distributor.address,
        [productId],
        id("m"),
        expiry,
        [id("wrong-head")],
        [id("h1")],
        id("op-stale")
      )
    ).to.be.revertedWithCustomError(contract, "HeadMismatch");
  });

  it("rejects duplicate product ids in a manifest", async function () {
    const { contract, manufacturer, distributor } = await deploy();
    const { productId, eventHash } = await registerOne(contract, manufacturer, "dup-item");
    const expiry = BigInt(await time.latest()) + 3600n;
    await expect(
      contract.connect(manufacturer).initiateTransfer(
        id("t-dup-item"),
        distributor.address,
        [productId, productId],
        id("m"),
        expiry,
        [eventHash, eventHash],
        [id("h1"), id("h2")],
        id("op-dup-item")
      )
    ).to.be.revertedWithCustomError(contract, "DuplicateProduct");
  });

  it("rejects an expired transfer on accept", async function () {
    const { contract, manufacturer, distributor } = await deploy();
    const { productId, eventHash } = await registerOne(contract, manufacturer, "exp");
    const now = await time.latest();
    const expiry = BigInt(now) + 10n;
    await contract.connect(manufacturer).initiateTransfer(
      id("t-exp"),
      distributor.address,
      [productId],
      id("m"),
      expiry,
      [eventHash],
      [id("h1")],
      id("op-i-exp")
    );
    await time.increaseTo(expiry + 1n);
    await expect(
      contract.connect(distributor).acceptTransfer(id("t-exp"), id("r"), [id("h2")], id("op-a-exp"))
    ).to.be.revertedWithCustomError(contract, "TransferExpired");
  });

  it("rejects a double accept", async function () {
    const { contract, manufacturer, distributor } = await deploy();
    const { productId, eventHash } = await registerOne(contract, manufacturer, "dbl");
    const expiry = BigInt(await time.latest()) + 3600n;
    const transferId = id("t-dbl");
    await contract.connect(manufacturer).initiateTransfer(
      transferId,
      distributor.address,
      [productId],
      id("m"),
      expiry,
      [eventHash],
      [id("h1")],
      id("op-i-dbl")
    );
    await contract.connect(distributor).acceptTransfer(transferId, id("r"), [id("h2")], id("op-a-dbl-1"));
    await expect(
      contract.connect(distributor).acceptTransfer(transferId, id("r2"), [id("h3")], id("op-a-dbl-2"))
    ).to.be.revertedWithCustomError(contract, "TransferClosed");
  });

  it("lets the recipient reject and the sender cancel", async function () {
    const { contract, manufacturer, distributor } = await deploy();
    const a = await registerOne(contract, manufacturer, "rej");
    const expiry = BigInt(await time.latest()) + 3600n;
    await contract.connect(manufacturer).initiateTransfer(
      id("t-rej"),
      distributor.address,
      [a.productId],
      id("m"),
      expiry,
      [a.eventHash],
      [id("h-init-rej")],
      id("op-i-rej")
    );
    await contract.connect(distributor).rejectTransfer(
      id("t-rej"),
      [id("h-init-rej")],
      [id("h-rej")],
      id("op-rej")
    );
    const afterReject = await contract.getProduct(a.productId);
    expect(afterReject.custodian).to.equal(manufacturer.address);
    expect(afterReject.reservedTransferId).to.equal(ZERO);

    const b = await registerOne(contract, manufacturer, "can");
    await contract.connect(manufacturer).initiateTransfer(
      id("t-can"),
      distributor.address,
      [b.productId],
      id("m"),
      expiry,
      [b.eventHash],
      [id("h-init-can")],
      id("op-i-can")
    );
    await contract.connect(manufacturer).cancelTransfer(
      id("t-can"),
      [id("h-init-can")],
      [id("h-can")],
      id("op-can")
    );
    const cancelled = await contract.getTransfer(id("t-can"));
    expect(cancelled.status).to.equal(TransferStatus.CANCELLED);
  });

  it("lets anyone expire a transfer after expiry", async function () {
    const { contract, manufacturer, distributor, outsider } = await deploy();
    const { productId, eventHash } = await registerOne(contract, manufacturer, "expire-me");
    const now = await time.latest();
    const expiry = BigInt(now) + 15n;
    await contract.connect(manufacturer).initiateTransfer(
      id("t-expire"),
      distributor.address,
      [productId],
      id("m"),
      expiry,
      [eventHash],
      [id("h-init-ex")],
      id("op-i-ex")
    );
    await expect(
      contract.connect(outsider).expireTransfer(id("t-expire"), [id("h-init-ex")], [id("h-ex")], id("op-ex-early"))
    ).to.be.revertedWithCustomError(contract, "NotExpired");
    await time.increaseTo(expiry + 1n);
    await contract.connect(distributor).expireTransfer(
      id("t-expire"),
      [id("h-init-ex")],
      [id("h-ex")],
      id("op-ex")
    );
    const rec = await contract.getTransfer(id("t-expire"));
    expect(rec.status).to.equal(TransferStatus.EXPIRED);
    const product = await contract.getProduct(productId);
    expect(product.reservedTransferId).to.equal(ZERO);
    expect(product.custodian).to.equal(manufacturer.address);
  });

  it("rejects a sale by a non-retailer custodian", async function () {
    const { contract, manufacturer } = await deploy();
    const { productId, eventHash } = await registerOne(contract, manufacturer, "sale-wrong");
    await expect(
      contract.connect(manufacturer).recordSale(productId, eventHash, id("h-sold"), id("op-sold"))
    ).to.be.revertedWithCustomError(contract, "UnauthorizedRole");
  });

  it("rejects a sale by a distributor who is the current custodian", async function () {
    const { contract, manufacturer, distributor } = await deploy();
    const { productId, eventHash } = await registerOne(contract, manufacturer, "sale-dist");
    const expiry = BigInt(await time.latest()) + 3600n;
    await contract.connect(manufacturer).initiateTransfer(
      id("t-sale-dist"),
      distributor.address,
      [productId],
      id("m"),
      expiry,
      [eventHash],
      [id("h1")],
      id("op-i-sd")
    );
    await contract.connect(distributor).acceptTransfer(
      id("t-sale-dist"),
      id("r"),
      [id("h2")],
      id("op-a-sd")
    );
    await expect(
      contract.connect(distributor).recordSale(productId, id("h2"), id("h-sold"), id("op-sold-dist"))
    ).to.be.revertedWithCustomError(contract, "UnauthorizedRole");
  });
});

