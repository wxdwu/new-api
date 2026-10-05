package demodata

import (
	"errors"
	"fmt"
	"testing"
	"time"

	"github.com/QuantumNous/new-api/common"
	"github.com/QuantumNous/new-api/model"
	"github.com/glebarez/sqlite"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"gorm.io/driver/mysql"
	"gorm.io/gorm"
)

func setupDemoDataTestDB(t *testing.T) *gorm.DB {
	t.Helper()

	db, err := gorm.Open(sqlite.Open(fmt.Sprintf("file:%s?mode=memory&cache=shared", t.Name())), &gorm.Config{})
	require.NoError(t, err)
	require.NoError(t, db.AutoMigrate(
		&model.User{},
		&model.Token{},
		&model.Channel{},
		&model.Ability{},
		&model.Vendor{},
		&model.Model{},
		&model.Option{},
		&model.Setup{},
		&model.Log{},
		&model.QuotaData{},
		&model.PerfMetric{},
	))

	previousDB := model.DB
	previousLogDB := model.LOG_DB
	common.SetDatabaseTypes(common.DatabaseTypeSQLite, common.DatabaseTypeSQLite)
	model.DB = db
	model.LOG_DB = db
	model.InitCol()
	t.Cleanup(func() {
		model.DB = previousDB
		model.LOG_DB = previousLogDB
	})
	return db
}

func demoConfig(now time.Time) Config {
	return Config{
		RootUsername: "demo-root",
		RootPassword: "LocalDemo123!",
		Now:          now,
	}
}

func countRows[T any](t *testing.T, db *gorm.DB) int64 {
	t.Helper()
	var count int64
	require.NoError(t, db.Model(new(T)).Count(&count).Error)
	return count
}

func TestSeedCreatesBrowsableDatasetAndValidCredentials(t *testing.T) {
	db := setupDemoDataTestDB(t)
	now := time.Date(2026, time.August, 26, 14, 0, 0, 0, time.UTC)

	summary, err := Seed(t.Context(), db, db, demoConfig(now))
	require.NoError(t, err)
	assert.Equal(t, Summary{
		Users:       4,
		Tokens:      6,
		Channels:    3,
		Models:      4,
		Abilities:   4,
		Logs:        14,
		QuotaRows:   28,
		MetricRows:  21,
		SeedVersion: CurrentSeedVersion,
	}, summary)

	login := model.User{Username: "demo-root", Password: "LocalDemo123!"}
	require.NoError(t, login.ValidateAndFill())
	assert.Equal(t, common.RoleRootUser, login.Role)
	assert.Equal(t, common.UserStatusEnabled, login.Status)

	var marker model.Option
	require.NoError(t, db.Where(&model.Option{Key: SeedMarkerKey}).First(&marker).Error)
	assert.Equal(t, CurrentSeedVersion, marker.Value)

	var setup model.Setup
	require.NoError(t, db.First(&setup).Error)
	assert.Equal(t, now.Unix(), setup.InitializedAt)

	wantOptions := map[string]string{
		"theme.frontend":       "default",
		"PasswordLoginEnabled": "true",
		"DataExportEnabled":    "true",
		"LogConsumeEnabled":    "true",
		"DemoSiteEnabled":      "false",
		"SelfUseModeEnabled":   "false",
	}
	for key, want := range wantOptions {
		var option model.Option
		require.NoError(t, db.Where(&model.Option{Key: key}).First(&option).Error)
		assert.Equal(t, want, option.Value, key)
	}

	var channels []model.Channel
	require.NoError(t, db.Order("id").Find(&channels).Error)
	require.Len(t, channels, 3)
	for _, channel := range channels {
		assert.Equal(t, common.ChannelStatusManuallyDisabled, channel.Status)
		assert.Equal(t, "http://127.0.0.1:9", channel.GetBaseURL())
		assert.NotContains(t, channel.Key, "sk-")
	}

	assert.EqualValues(t, 4, countRows[model.User](t, db))
	assert.EqualValues(t, 6, countRows[model.Token](t, db))
	assert.EqualValues(t, 3, countRows[model.Channel](t, db))
	assert.EqualValues(t, 4, countRows[model.Model](t, db))
	assert.EqualValues(t, 4, countRows[model.Ability](t, db))
	assert.EqualValues(t, 14, countRows[model.Log](t, db))
	assert.EqualValues(t, 28, countRows[model.QuotaData](t, db))
	assert.EqualValues(t, 21, countRows[model.PerfMetric](t, db))
}

func TestSeedIsIdempotentAndPreservesNonDemoRows(t *testing.T) {
	db := setupDemoDataTestDB(t)
	now := time.Date(2026, time.August, 26, 14, 0, 0, 0, time.UTC)
	require.NoError(t, seedWithoutSummary(t, db, demoConfig(now)))

	customPassword, err := common.Password2Hash("CustomPassword123!")
	require.NoError(t, err)
	customUser := model.User{
		Username:    "custom-user",
		Password:    customPassword,
		DisplayName: "Custom User",
		Role:        common.RoleCommonUser,
		Status:      common.UserStatusEnabled,
		Group:       "default",
		AffCode:     "custom-aff-code",
		Quota:       12345,
	}
	require.NoError(t, db.Create(&customUser).Error)

	summary, err := Seed(t.Context(), db, db, demoConfig(now.Add(24*time.Hour)))
	require.NoError(t, err)
	assert.Equal(t, 4, summary.Users)

	assert.EqualValues(t, 5, countRows[model.User](t, db))
	assert.EqualValues(t, 6, countRows[model.Token](t, db))
	assert.EqualValues(t, 3, countRows[model.Channel](t, db))
	assert.EqualValues(t, 14, countRows[model.Log](t, db))
	assert.EqualValues(t, 28, countRows[model.QuotaData](t, db))
	assert.EqualValues(t, 21, countRows[model.PerfMetric](t, db))

	var preserved model.User
	require.NoError(t, db.First(&preserved, customUser.Id).Error)
	assert.Equal(t, 12345, preserved.Quota)
	assert.Equal(t, "custom-aff-code", preserved.AffCode)
}

func TestSeedRefusesNonEmptyDatabaseWithoutMarker(t *testing.T) {
	db := setupDemoDataTestDB(t)
	password, err := common.Password2Hash("ExistingPassword123!")
	require.NoError(t, err)
	existing := model.User{
		Username:    "existing-root",
		Password:    password,
		DisplayName: "Existing Root",
		Role:        common.RoleRootUser,
		Status:      common.UserStatusEnabled,
		Group:       "default",
		AffCode:     "existing-aff-code",
	}
	require.NoError(t, db.Create(&existing).Error)

	_, err = Seed(t.Context(), db, db, demoConfig(time.Now()))
	require.Error(t, err)
	assert.True(t, errors.Is(err, ErrUnmarkedDatabaseNotEmpty))

	assert.EqualValues(t, 1, countRows[model.User](t, db))
	assert.EqualValues(t, 0, countRows[model.Channel](t, db))
	var markerCount int64
	require.NoError(t, db.Model(&model.Option{}).Where(&model.Option{Key: SeedMarkerKey}).Count(&markerCount).Error)
	assert.Zero(t, markerCount)
}

func TestHasSeedMarkerQuotesReservedKeyColumnForMySQL(t *testing.T) {
	db := setupMySQLDryRunDB(t)

	var query string
	require.NoError(t, db.Callback().Query().After("gorm:query").Register("capture-demo-marker-query", func(tx *gorm.DB) {
		query = tx.Statement.SQL.String()
	}))

	_, err := hasSeedMarker(db)
	require.NoError(t, err)
	assert.Contains(t, query, "`key` = ?")
}

func TestSeedTokensQuotesReservedKeyColumnForMySQL(t *testing.T) {
	db := setupMySQLDryRunDB(t)
	var deleteQuery string
	require.NoError(t, db.Callback().Delete().After("gorm:delete").Register("capture-demo-token-delete", func(tx *gorm.DB) {
		deleteQuery = tx.Statement.SQL.String()
	}))
	users := map[string]model.User{
		"demo-root":  {Id: 1, Username: "demo-root", Role: common.RoleRootUser},
		"demo-admin": {Id: 2, Username: "demo-admin", Role: common.RoleAdminUser},
		"demo-user":  {Id: 3, Username: "demo-user", Role: common.RoleCommonUser},
	}

	_, err := seedTokens(db, time.Date(2026, time.August, 28, 16, 0, 0, 0, time.UTC), users)
	require.NoError(t, err)
	assert.Contains(t, deleteQuery, "`key` IN")
}

func setupMySQLDryRunDB(t *testing.T) *gorm.DB {
	t.Helper()
	db, err := gorm.Open(mysql.New(mysql.Config{
		DSN:                       "root:password@tcp(127.0.0.1:3306)/new-api?parseTime=True",
		SkipInitializeWithVersion: true,
	}), &gorm.Config{DryRun: true, DisableAutomaticPing: true, SkipDefaultTransaction: true})
	require.NoError(t, err)
	return db
}

func seedWithoutSummary(t *testing.T, db *gorm.DB, cfg Config) error {
	t.Helper()
	_, err := Seed(t.Context(), db, db, cfg)
	return err
}
