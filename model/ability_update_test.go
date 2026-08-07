package model

import (
	"testing"

	"github.com/QuantumNous/new-api/common"
	"github.com/stretchr/testify/require"
)

func TestChannelUpdatePreservesExistingAbilityTag(t *testing.T) {
	truncateTables(t)

	channel := Channel{
		Type:     1,
		Key:      "local-test-key",
		Status:   common.ChannelStatusEnabled,
		Name:     "before update",
		Models:   "gpt-test-model",
		Group:    "default",
		Priority: common.GetPointer[int64](0),
		Weight:   common.GetPointer[uint](0),
	}
	require.NoError(t, channel.Insert())

	require.NoError(t, DB.Model(&Ability{}).
		Where("channel_id = ?", channel.Id).
		Update("tag", "1").Error)

	channel.Name = "after update"
	require.NoError(t, channel.Update())

	var ability Ability
	require.NoError(t, DB.Where(
		"channel_id = ? AND `group` = ? AND model = ?",
		channel.Id,
		"default",
		"gpt-test-model",
	).First(&ability).Error)
	require.NotNil(t, ability.Tag)
	require.Equal(t, "1", *ability.Tag)
}

func TestChannelUpdateReconcilesModelsWithoutOverwritingExistingTags(t *testing.T) {
	truncateTables(t)

	channelTag := "channel-tag"
	channel := Channel{
		Type:     1,
		Key:      "local-test-key",
		Status:   common.ChannelStatusEnabled,
		Name:     "model reconciliation",
		Models:   "keep-model,remove-model",
		Group:    "default",
		Tag:      &channelTag,
		Priority: common.GetPointer[int64](0),
		Weight:   common.GetPointer[uint](0),
	}
	require.NoError(t, channel.Insert())
	require.NoError(t, DB.Model(&Ability{}).
		Where("channel_id = ? AND model = ?", channel.Id, "keep-model").
		Update("tag", "ability-tag").Error)

	channel.Models = "keep-model,new-model"
	require.NoError(t, channel.Update())

	var abilities []Ability
	require.NoError(t, DB.Where("channel_id = ?", channel.Id).
		Order("model").Find(&abilities).Error)
	require.Len(t, abilities, 2)
	require.Equal(t, "keep-model", abilities[0].Model)
	require.NotNil(t, abilities[0].Tag)
	require.Equal(t, "ability-tag", *abilities[0].Tag)
	require.Equal(t, "new-model", abilities[1].Model)
	require.NotNil(t, abilities[1].Tag)
	require.Equal(t, "channel-tag", *abilities[1].Tag)
}

func TestChannelExplicitTagUpdateSynchronizesAbilityTags(t *testing.T) {
	truncateTables(t)

	channel := Channel{
		Type:     1,
		Key:      "local-test-key",
		Status:   common.ChannelStatusEnabled,
		Name:     "explicit tag update",
		Models:   "gpt-test-model",
		Group:    "default",
		Priority: common.GetPointer[int64](0),
		Weight:   common.GetPointer[uint](0),
	}
	require.NoError(t, channel.Insert())
	require.NoError(t, DB.Model(&Ability{}).
		Where("channel_id = ?", channel.Id).
		Update("tag", "ability-tag").Error)

	updatedTag := "updated-channel-tag"
	channel.Tag = &updatedTag
	require.NoError(t, channel.UpdateWithAbilityTagSync())

	var ability Ability
	require.NoError(t, DB.Where("channel_id = ?", channel.Id).First(&ability).Error)
	require.NotNil(t, ability.Tag)
	require.Equal(t, updatedTag, *ability.Tag)
}
