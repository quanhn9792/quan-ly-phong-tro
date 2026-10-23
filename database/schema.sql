/*
    Schema Quản lý cho thuê nhà / phòng.
    Script idempotent: chạy lại nhiều lần an toàn (python main.py init-db),
    chỉ tạo bảng/cột còn thiếu và cập nhật view, không ghi đè dữ liệu đang có.
*/

/* ===== Nhà / tòa nhà / căn hộ ===== */
IF OBJECT_ID(N'dbo.Properties', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.Properties
    (
        PropertyId INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_Properties PRIMARY KEY,
        PropertyName NVARCHAR(150) NOT NULL,
        PropertyType NVARCHAR(30) NOT NULL CONSTRAINT DF_Properties_PropertyType DEFAULT (N'ROOMING_HOUSE'),
        Address NVARCHAR(255) NULL,
        Note NVARCHAR(500) NULL,
        IsActive BIT NOT NULL CONSTRAINT DF_Properties_IsActive DEFAULT (1),
        CreatedAt DATETIME2(0) NOT NULL CONSTRAINT DF_Properties_CreatedAt DEFAULT (SYSDATETIME()),
        UpdatedAt DATETIME2(0) NULL,
        CONSTRAINT CK_Properties_PropertyType CHECK (PropertyType IN (N'ROOMING_HOUSE', N'WHOLE_HOUSE', N'APARTMENT', N'OTHER'))
    );
END;
GO

/* ===== Phòng / căn cho thuê (đơn vị tính tiền) ===== */
IF OBJECT_ID(N'dbo.Rooms', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.Rooms
    (
        RoomId INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_Rooms PRIMARY KEY,
        PropertyId INT NOT NULL,
        RoomCode NVARCHAR(20) NOT NULL,
        RoomName NVARCHAR(100) NOT NULL,
        RentAmount DECIMAL(18,2) NOT NULL,
        DefaultServiceFee DECIMAL(18,2) NOT NULL CONSTRAINT DF_Rooms_DefaultServiceFee DEFAULT (0),
        DefaultLaundryFee DECIMAL(18,2) NOT NULL CONSTRAINT DF_Rooms_DefaultLaundryFee DEFAULT (0),
        DefaultElectricityUnitPrice DECIMAL(18,2) NOT NULL CONSTRAINT DF_Rooms_DefaultElectricityUnitPrice DEFAULT (4000),
        DefaultWaterUnitPrice DECIMAL(18,2) NOT NULL CONSTRAINT DF_Rooms_DefaultWaterUnitPrice DEFAULT (25000),
        RentalStatus NVARCHAR(30) NOT NULL CONSTRAINT DF_Rooms_RentalStatus DEFAULT (N'VACANT'),
        IsActive BIT NOT NULL CONSTRAINT DF_Rooms_IsActive DEFAULT (1),
        CreatedAt DATETIME2(0) NOT NULL CONSTRAINT DF_Rooms_CreatedAt DEFAULT (SYSDATETIME()),
        UpdatedAt DATETIME2(0) NULL,
        CONSTRAINT FK_Rooms_Properties FOREIGN KEY (PropertyId) REFERENCES dbo.Properties (PropertyId),
        CONSTRAINT UQ_Rooms_Property_RoomCode UNIQUE (PropertyId, RoomCode),
        CONSTRAINT CK_Rooms_RentAmount CHECK (RentAmount >= 0),
        CONSTRAINT CK_Rooms_DefaultServiceFee CHECK (DefaultServiceFee >= 0),
        CONSTRAINT CK_Rooms_DefaultLaundryFee CHECK (DefaultLaundryFee >= 0),
        CONSTRAINT CK_Rooms_DefaultElectricityUnitPrice CHECK (DefaultElectricityUnitPrice >= 0),
        CONSTRAINT CK_Rooms_DefaultWaterUnitPrice CHECK (DefaultWaterUnitPrice >= 0),
        CONSTRAINT CK_Rooms_RentalStatus CHECK (RentalStatus IN (N'VACANT', N'OCCUPIED', N'RESERVED', N'MAINTENANCE', N'INACTIVE'))
    );
END;
GO

/* Nâng cấp DB cũ (chỉ có 1 nhà trọ): gắn toàn bộ phòng hiện có vào một nhà mặc định */
IF COL_LENGTH(N'dbo.Rooms', N'PropertyId') IS NULL
BEGIN
    ALTER TABLE dbo.Rooms ADD PropertyId INT NULL;
END;
GO

IF EXISTS (SELECT 1 FROM dbo.Rooms WHERE PropertyId IS NULL)
BEGIN
    IF NOT EXISTS (SELECT 1 FROM dbo.Properties)
        INSERT INTO dbo.Properties (PropertyName, PropertyType, Note)
        VALUES (N'Nhà trọ', N'ROOMING_HOUSE', N'Tạo tự động khi nâng cấp lên quản lý nhiều nhà');

    UPDATE dbo.Rooms
    SET PropertyId = (SELECT MIN(PropertyId) FROM dbo.Properties)
    WHERE PropertyId IS NULL;
END;
GO

IF EXISTS (SELECT 1 FROM sys.columns WHERE object_id = OBJECT_ID(N'dbo.Rooms') AND name = N'PropertyId' AND is_nullable = 1)
BEGIN
    ALTER TABLE dbo.Rooms ALTER COLUMN PropertyId INT NOT NULL;
END;
GO

IF OBJECT_ID(N'dbo.FK_Rooms_Properties', N'F') IS NULL
BEGIN
    ALTER TABLE dbo.Rooms WITH CHECK
        ADD CONSTRAINT FK_Rooms_Properties FOREIGN KEY (PropertyId) REFERENCES dbo.Properties (PropertyId);
END;
GO

/* Mã phòng chỉ cần duy nhất trong cùng một nhà (nhà A và nhà B đều có thể có phòng 101) */
IF OBJECT_ID(N'dbo.UQ_Rooms_RoomCode', N'UQ') IS NOT NULL
BEGIN
    ALTER TABLE dbo.Rooms DROP CONSTRAINT UQ_Rooms_RoomCode;
END;
GO

IF OBJECT_ID(N'dbo.UQ_Rooms_Property_RoomCode', N'UQ') IS NULL
BEGIN
    ALTER TABLE dbo.Rooms ADD CONSTRAINT UQ_Rooms_Property_RoomCode UNIQUE (PropertyId, RoomCode);
END;
GO

/* ===== Tháng tính tiền (đơn giá dự phòng) ===== */
IF OBJECT_ID(N'dbo.BillingMonths', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.BillingMonths
    (
        BillingMonthId INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_BillingMonths PRIMARY KEY,
        YearNumber SMALLINT NOT NULL,
        MonthNumber TINYINT NOT NULL,
        ElectricityUnitPrice DECIMAL(18,2) NOT NULL,
        WaterUnitPrice DECIMAL(18,2) NOT NULL,
        DefaultServiceFee DECIMAL(18,2) NOT NULL CONSTRAINT DF_BillingMonths_DefaultServiceFee DEFAULT (0),
        IsClosed BIT NOT NULL CONSTRAINT DF_BillingMonths_IsClosed DEFAULT (0),
        CreatedAt DATETIME2(0) NOT NULL CONSTRAINT DF_BillingMonths_CreatedAt DEFAULT (SYSDATETIME()),
        UpdatedAt DATETIME2(0) NULL,
        CONSTRAINT UQ_BillingMonths_YearMonth UNIQUE (YearNumber, MonthNumber),
        CONSTRAINT CK_BillingMonths_YearNumber CHECK (YearNumber BETWEEN 2000 AND 2100),
        CONSTRAINT CK_BillingMonths_MonthNumber CHECK (MonthNumber BETWEEN 1 AND 12),
        CONSTRAINT CK_BillingMonths_ElectricityUnitPrice CHECK (ElectricityUnitPrice >= 0),
        CONSTRAINT CK_BillingMonths_WaterUnitPrice CHECK (WaterUnitPrice >= 0),
        CONSTRAINT CK_BillingMonths_DefaultServiceFee CHECK (DefaultServiceFee >= 0)
    );
END;
GO

/* ===== Hóa đơn từng phòng theo tháng ===== */
IF OBJECT_ID(N'dbo.RoomMonthlyBills', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.RoomMonthlyBills
    (
        RoomMonthlyBillId INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_RoomMonthlyBills PRIMARY KEY,
        BillingMonthId INT NOT NULL,
        RoomId INT NOT NULL,
        RentAmount DECIMAL(18,2) NOT NULL,
        ServiceFee DECIMAL(18,2) NOT NULL,
        LaundryFee DECIMAL(18,2) NOT NULL CONSTRAINT DF_RoomMonthlyBills_LaundryFee DEFAULT (0),
        ElectricityUnitPrice DECIMAL(18,2) NOT NULL,
        WaterUnitPrice DECIMAL(18,2) NOT NULL,
        ElectricOld DECIMAL(18,2) NOT NULL,
        ElectricNew DECIMAL(18,2) NOT NULL,
        WaterOld DECIMAL(18,2) NOT NULL,
        WaterNew DECIMAL(18,2) NOT NULL,
        ElectricUsage AS (ElectricNew - ElectricOld) PERSISTED,
        WaterUsage AS (WaterNew - WaterOld) PERSISTED,
        ElectricityAmount AS ((ElectricNew - ElectricOld) * ElectricityUnitPrice) PERSISTED,
        WaterAmount AS ((WaterNew - WaterOld) * WaterUnitPrice) PERSISTED,
        TotalAmount AS
            (
                RentAmount
                + ServiceFee
                + LaundryFee
                + ((ElectricNew - ElectricOld) * ElectricityUnitPrice)
                + ((WaterNew - WaterOld) * WaterUnitPrice)
            ) PERSISTED,
        Note NVARCHAR(500) NULL,
        PaymentQrContent NVARCHAR(1000) NULL,
        CreatedAt DATETIME2(0) NOT NULL CONSTRAINT DF_RoomMonthlyBills_CreatedAt DEFAULT (SYSDATETIME()),
        UpdatedAt DATETIME2(0) NULL,
        CONSTRAINT FK_RoomMonthlyBills_BillingMonths FOREIGN KEY (BillingMonthId) REFERENCES dbo.BillingMonths (BillingMonthId),
        CONSTRAINT FK_RoomMonthlyBills_Rooms FOREIGN KEY (RoomId) REFERENCES dbo.Rooms (RoomId),
        CONSTRAINT UQ_RoomMonthlyBills_MonthRoom UNIQUE (BillingMonthId, RoomId),
        CONSTRAINT CK_RoomMonthlyBills_RentAmount CHECK (RentAmount >= 0),
        CONSTRAINT CK_RoomMonthlyBills_ServiceFee CHECK (ServiceFee >= 0),
        CONSTRAINT CK_RoomMonthlyBills_LaundryFee CHECK (LaundryFee >= 0),
        CONSTRAINT CK_RoomMonthlyBills_ElectricityUnitPrice CHECK (ElectricityUnitPrice >= 0),
        CONSTRAINT CK_RoomMonthlyBills_WaterUnitPrice CHECK (WaterUnitPrice >= 0),
        CONSTRAINT CK_RoomMonthlyBills_ElectricReading CHECK (ElectricNew >= ElectricOld),
        CONSTRAINT CK_RoomMonthlyBills_WaterReading CHECK (WaterNew >= WaterOld)
    );
END;
GO

/* ===== Cấu hình QR / email (1 dòng duy nhất) ===== */
IF OBJECT_ID(N'dbo.PaymentSettings', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.PaymentSettings
    (
        PaymentSettingsId TINYINT NOT NULL CONSTRAINT PK_PaymentSettings PRIMARY KEY,
        QrImage VARBINARY(MAX) NULL,
        QrMimeType NVARCHAR(100) NULL,
        QrFileName NVARCHAR(255) NULL,
        AccountInfo NVARCHAR(500) NULL,
        SenderName NVARCHAR(255) NULL,
        FromEmail NVARCHAR(255) NULL,
        SmtpHost NVARCHAR(255) NULL,
        SmtpPort INT NULL,
        SmtpUseTls BIT NOT NULL CONSTRAINT DF_PaymentSettings_SmtpUseTls DEFAULT (1),
        SmtpUsername NVARCHAR(255) NULL,
        SmtpPassword NVARCHAR(500) NULL,
        UpdatedAt DATETIME2(0) NULL,
        CONSTRAINT CK_PaymentSettings_Singleton CHECK (PaymentSettingsId = 1)
    );
END;
GO

IF NOT EXISTS (SELECT 1 FROM dbo.PaymentSettings WHERE PaymentSettingsId = 1)
BEGIN
    INSERT INTO dbo.PaymentSettings (PaymentSettingsId) VALUES (1);
END;
GO

/* ===== Lịch sử gửi hóa đơn ===== */
IF OBJECT_ID(N'dbo.BillDeliveryLogs', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.BillDeliveryLogs
    (
        BillDeliveryLogId INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_BillDeliveryLogs PRIMARY KEY,
        RoomMonthlyBillId INT NOT NULL,
        Channel NVARCHAR(30) NOT NULL,
        Recipient NVARCHAR(255) NULL,
        Status NVARCHAR(30) NOT NULL,
        ErrorMessage NVARCHAR(1000) NULL,
        SentAt DATETIME2(0) NOT NULL CONSTRAINT DF_BillDeliveryLogs_SentAt DEFAULT (SYSDATETIME()),
        CONSTRAINT FK_BillDeliveryLogs_RoomMonthlyBills FOREIGN KEY (RoomMonthlyBillId) REFERENCES dbo.RoomMonthlyBills (RoomMonthlyBillId),
        CONSTRAINT CK_BillDeliveryLogs_Channel CHECK (Channel IN (N'EMAIL', N'ZALO', N'EXPORT')),
        CONSTRAINT CK_BillDeliveryLogs_Status CHECK (Status IN (N'SENT', N'FAILED', N'EXPORTED'))
    );
END;
GO

/* ===== Giai đoạn đơn giá theo phòng ===== */
IF OBJECT_ID(N'dbo.RoomPricePeriods', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.RoomPricePeriods
    (
        RoomPricePeriodId INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_RoomPricePeriods PRIMARY KEY,
        RoomId INT NOT NULL,
        EffectiveFromYear SMALLINT NOT NULL,
        EffectiveFromMonth TINYINT NOT NULL,
        EffectiveToYear SMALLINT NULL,
        EffectiveToMonth TINYINT NULL,
        RentAmount DECIMAL(18,2) NOT NULL,
        ServiceFee DECIMAL(18,2) NOT NULL CONSTRAINT DF_RoomPricePeriods_ServiceFee DEFAULT (0),
        LaundryFee DECIMAL(18,2) NOT NULL CONSTRAINT DF_RoomPricePeriods_LaundryFee DEFAULT (0),
        ElectricityUnitPrice DECIMAL(18,2) NOT NULL,
        WaterUnitPrice DECIMAL(18,2) NOT NULL,
        Note NVARCHAR(500) NULL,
        CreatedAt DATETIME2(0) NOT NULL CONSTRAINT DF_RoomPricePeriods_CreatedAt DEFAULT (SYSDATETIME()),
        UpdatedAt DATETIME2(0) NULL,
        CONSTRAINT FK_RoomPricePeriods_Rooms FOREIGN KEY (RoomId) REFERENCES dbo.Rooms (RoomId),
        CONSTRAINT UQ_RoomPricePeriods_RoomStart UNIQUE (RoomId, EffectiveFromYear, EffectiveFromMonth),
        CONSTRAINT CK_RoomPricePeriods_FromYear CHECK (EffectiveFromYear BETWEEN 2000 AND 2100),
        CONSTRAINT CK_RoomPricePeriods_FromMonth CHECK (EffectiveFromMonth BETWEEN 1 AND 12),
        CONSTRAINT CK_RoomPricePeriods_ToYear CHECK (EffectiveToYear IS NULL OR EffectiveToYear BETWEEN 2000 AND 2100),
        CONSTRAINT CK_RoomPricePeriods_ToMonth CHECK (EffectiveToMonth IS NULL OR EffectiveToMonth BETWEEN 1 AND 12),
        CONSTRAINT CK_RoomPricePeriods_ToBothOrNone CHECK
        (
            (EffectiveToYear IS NULL AND EffectiveToMonth IS NULL)
            OR (EffectiveToYear IS NOT NULL AND EffectiveToMonth IS NOT NULL)
        ),
        CONSTRAINT CK_RoomPricePeriods_DateRange CHECK
        (
            EffectiveToYear IS NULL
            OR EffectiveToYear > EffectiveFromYear
            OR (EffectiveToYear = EffectiveFromYear AND EffectiveToMonth >= EffectiveFromMonth)
        ),
        CONSTRAINT CK_RoomPricePeriods_RentAmount CHECK (RentAmount >= 0),
        CONSTRAINT CK_RoomPricePeriods_ServiceFee CHECK (ServiceFee >= 0),
        CONSTRAINT CK_RoomPricePeriods_LaundryFee CHECK (LaundryFee >= 0),
        CONSTRAINT CK_RoomPricePeriods_ElectricityUnitPrice CHECK (ElectricityUnitPrice >= 0),
        CONSTRAINT CK_RoomPricePeriods_WaterUnitPrice CHECK (WaterUnitPrice >= 0)
    );
END;
GO

/* Phòng chưa có giai đoạn nào: tạo giai đoạn gốc (01/2000) từ giá mặc định của phòng */
INSERT INTO dbo.RoomPricePeriods
    (RoomId, EffectiveFromYear, EffectiveFromMonth, RentAmount, ServiceFee, LaundryFee, ElectricityUnitPrice, WaterUnitPrice, Note)
SELECT
    r.RoomId, 2000, 1, r.RentAmount, r.DefaultServiceFee, r.DefaultLaundryFee,
    r.DefaultElectricityUnitPrice, r.DefaultWaterUnitPrice, N'Gia mac dinh tu thong tin phong'
FROM dbo.Rooms AS r
WHERE NOT EXISTS (SELECT 1 FROM dbo.RoomPricePeriods AS p WHERE p.RoomId = r.RoomId);
GO

/* ===== Khách thuê (mỗi dòng là một lượt thuê) ===== */
IF OBJECT_ID(N'dbo.Tenants', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.Tenants
    (
        TenantId INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_Tenants PRIMARY KEY,
        RoomId INT NOT NULL,
        FullName NVARCHAR(120) NOT NULL,
        Phone NVARCHAR(30) NULL,
        Email NVARCHAR(255) NULL,
        ZaloPhone NVARCHAR(30) NULL,
        ZaloUserId NVARCHAR(100) NULL,
        CitizenId NVARCHAR(30) NULL,
        PermanentAddress NVARCHAR(255) NULL,
        MoveInDate DATE NULL,
        MoveOutDate DATE NULL,
        RentAmount DECIMAL(18,2) NOT NULL CONSTRAINT DF_Tenants_RentAmount DEFAULT (0),
        ServiceFee DECIMAL(18,2) NOT NULL CONSTRAINT DF_Tenants_ServiceFee DEFAULT (0),
        IsCurrent BIT NOT NULL CONSTRAINT DF_Tenants_IsCurrent DEFAULT (1),
        Note NVARCHAR(500) NULL,
        CreatedAt DATETIME2(0) NOT NULL CONSTRAINT DF_Tenants_CreatedAt DEFAULT (SYSDATETIME()),
        UpdatedAt DATETIME2(0) NULL,
        CONSTRAINT FK_Tenants_Rooms FOREIGN KEY (RoomId) REFERENCES dbo.Rooms (RoomId),
        CONSTRAINT CK_Tenants_MoveOutDate CHECK (MoveOutDate IS NULL OR MoveInDate IS NULL OR MoveOutDate >= MoveInDate),
        CONSTRAINT CK_Tenants_RentAmount CHECK (RentAmount >= 0),
        CONSTRAINT CK_Tenants_ServiceFee CHECK (ServiceFee >= 0)
    );
END;
GO

/* ===== Views ===== */
CREATE OR ALTER VIEW dbo.v_CurrentRoomTenants
AS
SELECT
    r.RoomId,
    ISNULL(tenant_count.CurrentTenantCount, 0) AS CurrentTenantCount,
    tenant_count.TenantNames
FROM dbo.Rooms AS r
OUTER APPLY
(
    SELECT
        COUNT_BIG(*) AS CurrentTenantCount,
        STRING_AGG(t.FullName, N', ') WITHIN GROUP (ORDER BY t.FullName) AS TenantNames
    FROM dbo.Tenants AS t
    WHERE t.RoomId = r.RoomId
      AND t.IsCurrent = 1
) AS tenant_count;
GO

/*
    Hóa đơn theo tháng. Khách thuê được lấy theo NGÀY THUÊ khớp với tháng của hóa đơn
    (MoveInDate <= cuối tháng và MoveOutDate >= đầu tháng), không phải khách đang thuê hiện tại,
    nên hóa đơn tháng cũ luôn hiện đúng người thuê lúc đó.
*/
CREATE OR ALTER VIEW dbo.v_MonthlyRoomBills
AS
SELECT
    b.RoomMonthlyBillId,
    b.BillingMonthId,
    b.RoomId,
    bm.YearNumber,
    bm.MonthNumber,
    r.PropertyId,
    p.PropertyName,
    p.PropertyType,
    r.RoomCode,
    r.RoomName,
    r.RentalStatus,
    month_tenants.TenantNames,
    contact.Email AS TenantEmail,
    contact.Phone AS TenantPhone,
    contact.ZaloPhone AS TenantZaloPhone,
    contact.ZaloUserId AS TenantZaloUserId,
    b.RentAmount,
    b.ServiceFee,
    b.LaundryFee,
    b.ElectricOld,
    b.ElectricNew,
    b.ElectricUsage,
    b.ElectricityUnitPrice,
    b.ElectricityAmount,
    b.WaterOld,
    b.WaterNew,
    b.WaterUsage,
    b.WaterUnitPrice,
    b.WaterAmount,
    -- Tự cộng lại: ở DB cũ cột tính sẵn RoomMonthlyBills.TotalAmount được tạo trước khi có LaundryFee nên không gồm phí giặt.
    (b.RentAmount + b.ServiceFee + b.LaundryFee + b.ElectricityAmount + b.WaterAmount) AS TotalAmount,
    b.Note,
    b.PaymentQrContent,
    b.CreatedAt,
    b.UpdatedAt
FROM dbo.RoomMonthlyBills AS b
INNER JOIN dbo.BillingMonths AS bm
    ON bm.BillingMonthId = b.BillingMonthId
INNER JOIN dbo.Rooms AS r
    ON r.RoomId = b.RoomId
INNER JOIN dbo.Properties AS p
    ON p.PropertyId = r.PropertyId
CROSS APPLY
(
    SELECT
        DATEFROMPARTS(bm.YearNumber, bm.MonthNumber, 1) AS MonthStart,
        EOMONTH(DATEFROMPARTS(bm.YearNumber, bm.MonthNumber, 1)) AS MonthEnd
) AS period
OUTER APPLY
(
    SELECT STRING_AGG(t.FullName, N', ') WITHIN GROUP (ORDER BY t.FullName) AS TenantNames
    FROM dbo.Tenants AS t
    WHERE t.RoomId = b.RoomId
      AND (t.MoveInDate IS NULL OR t.MoveInDate <= period.MonthEnd)
      AND (t.MoveOutDate IS NULL OR t.MoveOutDate >= period.MonthStart)
) AS month_tenants
OUTER APPLY
(
    SELECT TOP 1 t.Email, t.Phone, t.ZaloPhone, t.ZaloUserId
    FROM dbo.Tenants AS t
    WHERE t.RoomId = b.RoomId
      AND (t.MoveInDate IS NULL OR t.MoveInDate <= period.MonthEnd)
      AND (t.MoveOutDate IS NULL OR t.MoveOutDate >= period.MonthStart)
    ORDER BY
        CASE WHEN t.MoveInDate IS NULL THEN 1 ELSE 0 END,
        t.MoveInDate DESC,
        t.TenantId DESC
) AS contact;
GO
