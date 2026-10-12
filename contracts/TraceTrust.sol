// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title TraceTrust supply-chain commitments
/// @notice Roles are msg.sender org accounts registered by governance.
///         Event hashes are SHA-256 commitments computed off-chain.
contract TraceTrust {
    enum Role {
        NONE,
        MANUFACTURER,
        DISTRIBUTOR,
        RETAILER
    }

    enum Lifecycle {
        NONE,
        REGISTERED,
        IN_SUPPLY_CHAIN,
        SOLD
    }

    enum TransferStatus {
        NONE,
        INITIATED,
        ACCEPTED,
        REJECTED,
        CANCELLED,
        EXPIRED
    }

    struct Organization {
        Role role;
        bool active;
        bool exists;
    }

    struct Product {
        address custodian;
        Lifecycle lifecycle;
        uint64 seq;
        bytes32 eventHead;
        bytes32 reservedTransferId;
        bool exists;
    }

    struct TransferRec {
        address sender;
        address recipient;
        bytes32[] productIds;
        bytes32 manifestDigest;
        uint64 expiresAt;
        TransferStatus status;
        bool exists;
    }

    address public immutable governance;
    bytes32 public immutable deploymentSalt;

    mapping(address => Organization) public organizations;
    mapping(bytes32 => Product) private _products;
    mapping(bytes32 => TransferRec) private _transfers;
    mapping(bytes32 => bool) public usedOperations;

    event OrganizationRegistered(address indexed account, Role role, bool active);
    event OrganizationStatusChanged(address indexed account, bool active);
    event ProductRegistered(bytes32 indexed productId, bytes32 indexed operationUid, bytes32 eventHash, uint64 seq);
    event TransferInitiated(bytes32 indexed transferId, bytes32 indexed operationUid, address sender, address recipient);
    event TransferAccepted(bytes32 indexed transferId, bytes32 indexed operationUid, address recipient);
    event TransferTerminated(bytes32 indexed transferId, bytes32 indexed operationUid, TransferStatus status);
    event ProductSold(bytes32 indexed productId, bytes32 indexed operationUid, bytes32 eventHash);
    event EventCommitted(
        bytes32 indexed productId,
        bytes32 indexed operationUid,
        bytes32 eventHash,
        uint64 seq,
        bytes32 previousHead
    );

    error NotGovernance();
    error InactiveOrg();
    error UnauthorizedRole();
    error ProductExists();
    error ProductUnknown();
    error DuplicateProduct();
    error DuplicateOperation();
    error ZeroId();
    error NotCustodian();
    error IllegalEdge();
    error Reserved();
    error ManifestSize();
    error HeadMismatch();
    error TransferUnknown();
    error NotRecipient();
    error NotSender();
    error NotExpired();
    error TransferExpired();
    error TransferClosed();
    error SaleNotRetailer();
    error ActiveTransfer();
    error AlreadySold();
    error LengthMismatch();

    modifier onlyGovernance() {
        if (msg.sender != governance) revert NotGovernance();
        _;
    }

    modifier uniqueOp(bytes32 operationUid) {
        if (operationUid == bytes32(0)) revert ZeroId();
        if (usedOperations[operationUid]) revert DuplicateOperation();
        usedOperations[operationUid] = true;
        _;
    }

    constructor(bytes32 salt) {
        governance = msg.sender;
        deploymentSalt = salt;
    }

    function registerOrganization(address account, Role role, bool active) external onlyGovernance {
        if (account == address(0) || role == Role.NONE) revert UnauthorizedRole();
        organizations[account] = Organization({role: role, active: active, exists: true});
        emit OrganizationRegistered(account, role, active);
    }

    function setOrganizationActive(address account, bool active) external onlyGovernance {
        if (!organizations[account].exists) revert InactiveOrg();
        organizations[account].active = active;
        emit OrganizationStatusChanged(account, active);
    }

    function registerProduct(bytes32 productId, bytes32 eventHash, bytes32 operationUid)
        external
        uniqueOp(operationUid)
    {
        _requireActive(msg.sender, Role.MANUFACTURER);
        if (productId == bytes32(0) || eventHash == bytes32(0)) revert ZeroId();
        if (_products[productId].exists) revert ProductExists();
        _products[productId] = Product({
            custodian: msg.sender,
            lifecycle: Lifecycle.REGISTERED,
            seq: 0,
            eventHead: eventHash,
            reservedTransferId: bytes32(0),
            exists: true
        });
        emit ProductRegistered(productId, operationUid, eventHash, 0);
        emit EventCommitted(productId, operationUid, eventHash, 0, bytes32(0));
    }

    function initiateTransfer(
        bytes32 transferId,
        address recipient,
        bytes32[] calldata productIds,
        bytes32 manifestDigest,
        uint64 expiresAt,
        bytes32[] calldata expectedHeads,
        bytes32[] calldata newEventHashes,
        bytes32 operationUid
    ) external uniqueOp(operationUid) {
        _requireActiveOrg(msg.sender);
        if (transferId == bytes32(0) || manifestDigest == bytes32(0)) revert ZeroId();
        if (_transfers[transferId].exists) revert TransferClosed();
        uint256 n = productIds.length;
        if (n == 0 || n > 20) revert ManifestSize();
        if (expectedHeads.length != n || newEventHashes.length != n) revert LengthMismatch();
        if (expiresAt <= block.timestamp) revert TransferExpired();
        Organization memory senderOrg = organizations[msg.sender];
        Organization memory recipientOrg = organizations[recipient];
        if (!recipientOrg.active) revert InactiveOrg();
        if (!_legalEdge(senderOrg.role, recipientOrg.role)) revert IllegalEdge();

        for (uint256 i = 0; i < n; i++) {
            bytes32 pid = productIds[i];
            if (pid == bytes32(0) || newEventHashes[i] == bytes32(0)) revert ZeroId();
            for (uint256 j = 0; j < i; j++) {
                if (productIds[j] == pid) revert DuplicateProduct();
            }
            Product storage product = _products[pid];
            if (!product.exists) revert ProductUnknown();
            if (product.custodian != msg.sender) revert NotCustodian();
            if (product.reservedTransferId != bytes32(0)) revert Reserved();
            if (product.lifecycle == Lifecycle.SOLD) revert AlreadySold();
            if (product.eventHead != expectedHeads[i]) revert HeadMismatch();
            bytes32 previous = product.eventHead;
            product.seq += 1;
            product.eventHead = newEventHashes[i];
            product.reservedTransferId = transferId;
            emit EventCommitted(pid, operationUid, newEventHashes[i], product.seq, previous);
        }

        TransferRec storage rec = _transfers[transferId];
        rec.sender = msg.sender;
        rec.recipient = recipient;
        rec.productIds = productIds;
        rec.manifestDigest = manifestDigest;
        rec.expiresAt = expiresAt;
        rec.status = TransferStatus.INITIATED;
        rec.exists = true;
        emit TransferInitiated(transferId, operationUid, msg.sender, recipient);
    }

    function acceptTransfer(
        bytes32 transferId,
        bytes32 receiptDigest,
        bytes32[] calldata newEventHashes,
        bytes32 operationUid
    ) external uniqueOp(operationUid) {
        TransferRec storage rec = _requireOpenTransfer(transferId);
        if (msg.sender != rec.recipient) revert NotRecipient();
        _requireActiveOrg(msg.sender);
        if (block.timestamp > rec.expiresAt) revert TransferExpired();
        if (receiptDigest == bytes32(0)) revert ZeroId();
        uint256 n = rec.productIds.length;
        if (newEventHashes.length != n) revert LengthMismatch();
        for (uint256 i = 0; i < n; i++) {
            if (newEventHashes[i] == bytes32(0)) revert ZeroId();
            Product storage product = _products[rec.productIds[i]];
            if (product.reservedTransferId != transferId) revert Reserved();
            if (product.custodian != rec.sender) revert NotCustodian();
            bytes32 previous = product.eventHead;
            product.seq += 1;
            product.eventHead = newEventHashes[i];
            product.custodian = rec.recipient;
            product.reservedTransferId = bytes32(0);
            product.lifecycle = Lifecycle.IN_SUPPLY_CHAIN;
            emit EventCommitted(rec.productIds[i], operationUid, newEventHashes[i], product.seq, previous);
        }
        rec.status = TransferStatus.ACCEPTED;
        emit TransferAccepted(transferId, operationUid, rec.recipient);
    }

    function rejectTransfer(
        bytes32 transferId,
        bytes32[] calldata expectedHeads,
        bytes32[] calldata newEventHashes,
        bytes32 operationUid
    ) external uniqueOp(operationUid) {
        TransferRec storage rec = _requireOpenTransfer(transferId);
        if (msg.sender != rec.recipient) revert NotRecipient();
        _requireActiveOrg(msg.sender);
        _terminate(rec, transferId, expectedHeads, newEventHashes, operationUid, TransferStatus.REJECTED);
    }

    function cancelTransfer(
        bytes32 transferId,
        bytes32[] calldata expectedHeads,
        bytes32[] calldata newEventHashes,
        bytes32 operationUid
    ) external uniqueOp(operationUid) {
        TransferRec storage rec = _requireOpenTransfer(transferId);
        if (msg.sender != rec.sender) revert NotSender();
        _requireActiveOrg(msg.sender);
        _terminate(rec, transferId, expectedHeads, newEventHashes, operationUid, TransferStatus.CANCELLED);
    }

    function expireTransfer(
        bytes32 transferId,
        bytes32[] calldata expectedHeads,
        bytes32[] calldata newEventHashes,
        bytes32 operationUid
    ) external uniqueOp(operationUid) {
        TransferRec storage rec = _requireOpenTransfer(transferId);
        if (block.timestamp <= rec.expiresAt) revert NotExpired();
        _terminate(rec, transferId, expectedHeads, newEventHashes, operationUid, TransferStatus.EXPIRED);
    }

    function recordSale(bytes32 productId, bytes32 expectedHead, bytes32 eventHash, bytes32 operationUid)
        external
        uniqueOp(operationUid)
    {
        _requireActive(msg.sender, Role.RETAILER);
        if (productId == bytes32(0) || eventHash == bytes32(0)) revert ZeroId();
        Product storage product = _products[productId];
        if (!product.exists) revert ProductUnknown();
        if (product.custodian != msg.sender) revert NotCustodian();
        if (organizations[msg.sender].role != Role.RETAILER) revert SaleNotRetailer();
        if (product.reservedTransferId != bytes32(0)) revert ActiveTransfer();
        if (product.lifecycle == Lifecycle.SOLD) revert AlreadySold();
        if (product.eventHead != expectedHead) revert HeadMismatch();
        bytes32 previous = product.eventHead;
        product.seq += 1;
        product.eventHead = eventHash;
        product.lifecycle = Lifecycle.SOLD;
        emit ProductSold(productId, operationUid, eventHash);
        emit EventCommitted(productId, operationUid, eventHash, product.seq, previous);
    }

    function getProduct(bytes32 productId)
        external
        view
        returns (address custodian, Lifecycle lifecycle, uint64 seq, bytes32 eventHead, bytes32 reservedTransferId, bool exists)
    {
        Product storage product = _products[productId];
        return (product.custodian, product.lifecycle, product.seq, product.eventHead, product.reservedTransferId, product.exists);
    }

    function getTransfer(bytes32 transferId)
        external
        view
        returns (
            address sender,
            address recipient,
            bytes32[] memory productIds,
            bytes32 manifestDigest,
            uint64 expiresAt,
            TransferStatus status
        )
    {
        TransferRec storage rec = _transfers[transferId];
        return (rec.sender, rec.recipient, rec.productIds, rec.manifestDigest, rec.expiresAt, rec.status);
    }

    function _terminate(
        TransferRec storage rec,
        bytes32 transferId,
        bytes32[] calldata expectedHeads,
        bytes32[] calldata newEventHashes,
        bytes32 operationUid,
        TransferStatus next
    ) internal {
        uint256 n = rec.productIds.length;
        if (expectedHeads.length != n || newEventHashes.length != n) revert LengthMismatch();
        for (uint256 i = 0; i < n; i++) {
            if (newEventHashes[i] == bytes32(0)) revert ZeroId();
            Product storage product = _products[rec.productIds[i]];
            if (product.reservedTransferId != transferId) revert Reserved();
            if (product.eventHead != expectedHeads[i]) revert HeadMismatch();
            bytes32 previous = product.eventHead;
            product.seq += 1;
            product.eventHead = newEventHashes[i];
            product.reservedTransferId = bytes32(0);
            emit EventCommitted(rec.productIds[i], operationUid, newEventHashes[i], product.seq, previous);
        }
        rec.status = next;
        emit TransferTerminated(transferId, operationUid, next);
    }

    function _requireOpenTransfer(bytes32 transferId) internal view returns (TransferRec storage rec) {
        rec = _transfers[transferId];
        if (!rec.exists) revert TransferUnknown();
        if (rec.status != TransferStatus.INITIATED) revert TransferClosed();
    }

    function _requireActiveOrg(address account) internal view {
        if (!organizations[account].active) revert InactiveOrg();
    }

    function _requireActive(address account, Role role) internal view {
        Organization memory org = organizations[account];
        if (!org.active) revert InactiveOrg();
        if (org.role != role) revert UnauthorizedRole();
    }

    function _legalEdge(Role sender, Role recipient) internal pure returns (bool) {
        return (sender == Role.MANUFACTURER && recipient == Role.DISTRIBUTOR)
            || (sender == Role.DISTRIBUTOR && recipient == Role.RETAILER);
    }
}
