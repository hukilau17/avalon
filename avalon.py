# Avalon discord bot
# Matthew Kroesche

import discord
import recordclass
import enum
import sys
import io
import datetime
import re
import pickle
import traceback
import random
import itertools
import asyncio



GOOD = True
EVIL = False

APPROVE = True
REJECT = False

SUCCESS = True
FAIL = False




class Role(enum.Enum):
    # Various player roles in the game
    SERVANT = 1
    MINION = 2
    MERLIN = 3
    ASSASSIN = 4
    MORGANA = 5
    PERCIVAL = 6
    MORDRED = 7
    OBERON = 8
    NOREBO = 9
    PALM = 10



GOOD_ROLES = [Role.SERVANT, Role.MERLIN, Role.PERCIVAL, Role.NOREBO, Role.PALM]
EVIL_ROLES = [Role.MINION, Role.ASSASSIN, Role.MORGANA, Role.MORDRED, Role.OBERON]



ROLE_NAMES = [
    # Descriptive names for all the roles
    'None',
    'Loyal Servant of Arthur',
    'Minion of Mordred',
    'Merlin',
    'Assassin',
    'Morgana',
    'Percival',
    'Mordred',
    'Oberon',
    'Norebo',
    'Palm',
    ]


ROLE_COMMANDS = [
    # Command names for all the roles
    'none',
    'servant',
    'minion',
    'merlin',
    'assassin',
    'morgana',
    'percival',
    'mordred',
    'oberon',
    'norebo',
    'palm',
    ]



FEATURE_NAMES = {
    # Descriptive names for all the features
    'merlin': 'Merlin',
    'morgana': 'Morgana/Percival',
    'mordred': 'Mordred',
    'oberon': 'Oberon',
    'norebo': 'Norebo',
    'palm': 'Palm',
    'lady': 'Lady of the Lake',
    }


MENTION_RE = re.compile(r'<@!?(\d+)>')
STATS_RE = re.compile(r'^<@!?(\d+)>: ([\w /]+)$', re.M)



Player = recordclass.recordclass('Player', 'user role side vote outcome')
# user: the discord.User controlling this player.
# role: the Role of this player.
# side: True if this player is good, False if they are evil.
# vote: True for an approve vote, False for a reject.
# outcome: True for a success outcome, False for a fail.



# Game parameters

N_EVIL = {
    5 : 2,
    6 : 2,
    7 : 3,
    8 : 3,
    9 : 3,
    10: 4,
    }

QUEST_LISTS = {
    5 : [(2, 1), (3, 1), (2, 1), (3, 1), (3, 1)],
    6 : [(2, 1), (3, 1), (4, 1), (3, 1), (4, 1)],
    7 : [(2, 1), (3, 1), (3, 1), (4, 2), (4, 1)],
    8 : [(3, 1), (4, 1), (4, 1), (5, 2), (5, 1)],
    9 : [(3, 1), (4, 1), (4, 1), (5, 2), (5, 1)],
    10: [(3, 1), (4, 1), (4, 1), (5, 2), (5, 1)],
    }








class Avalon(discord.Client):

    TOKEN = 'nice try'
    DEFAULT_CHANNEL = 437391702165291028 # avalon bot channel
    PING_CHANNEL = 650900503517069335 # off-topic channel for pinging
    ROLE_ID = 697637135414591569 # Avalon role ID for pinging
    PING_DELAY = datetime.timedelta(hours=1) # One-hour ping delay
    VOTE_DELAY = 15 # Number of seconds before voting messages are deleted


    def __init__(self):
        discord.Client.__init__(self)
        self.main_channel = None # The default channel to post messages in
        self.owner = None # The player who started the game
        self.running = False # True if the game is currently ongoing
        self.last_ping = None # Keep a delay on pings in #off-topic so they don't flood it
        self.muted = False # True if we are playing a silent game
        self.fetching_stats = False # True if the bot is busy fetching stats
        self.spotify_mode = False # True if the bot is in Spotify mode
        self.cmd_lookup = {}
        self.help = '**Avalon bot commands:**\n'
        snips = set()
        for fname in dir(self):
            if not fname.startswith('av_'):
                continue
            func = getattr(self, fname)
            name = fname[3:]
            self.cmd_lookup[name] = func
            if not ((func.__name__ == fname) and func.__doc__):
                continue
            snipsize = 1
            while name[:snipsize] in snips:
                snipsize += 1
                if snipsize == len(name):
                    snipsize = 0
                    break
            if snipsize:
                snips.add(name[:snipsize])
                self.cmd_lookup[name[:snipsize]] = func
            self.help += '\nav __%s__%s: %s' % (name[:snipsize], name[snipsize:], func.__doc__)


    async def on_message(self, message):
        # Top-level coroutine to reply to bot commands
        # This bot does not reply to itself
        if message.author == self.user:
            return
        # Find the main channel
        if self.main_channel is None:
            self.main_channel = discord.utils.get(self.get_all_channels(), id=self.DEFAULT_CHANNEL)
        # This bot only replies to "av" commands
        if not message.content.lower().startswith('av '):
            return
        command = message.content.split(None, 2)[1].lower()
        if command in self.cmd_lookup:
            await self.cmd_lookup[command](message)
        if self.muted and self.running and (message.channel == self.main_channel):
            await message.delete()




    ##### Convenience functions that are called by bot commands #####


    async def askyesno(self, question, user, channel):
        # Ask a yes/no question.
        await channel.send(question + ' (Yes/No)')
        def check(m):
            return (m.channel == channel) and (m.author == user) and (m.content.lower().strip() in ('yes', 'no'))
        try:
            yesno = await self.wait_for('message', check=check, timeout=10)
        except asyncio.TimeoutError:
            return False # Guess not, then
        return yesno.content.lower().strip() == 'yes'


    async def check_game(self, message):
        # Returns True if there is a game; else prints an error message and returns False
        if self.owner:
            return True
        await message.channel.send('There is no active game right now.')
        return False


    async def check_owner(self, message):
        # Returns True if there is a game and the person who sent this message created it; else prints an error message and returns False
        if (await self.check_game(message)):
            if self.owner.user == message.author:
                return True
            await message.channel.send('This game was created by %s. You do not have permission to modify it.' % self.owner.user.mention)
        return False
    

    async def check_running(self, message):
        # Returns True if there is a game and it has been started; else prints an error message and returns False
        if (await self.check_game(message)):
            if self.running:
                return True
            await message.channel.send('This game has not started yet.')
        return False
    

    async def check_not_running(self, message):
        # Returns True if there is a game and it has not yet started; else prints an error message and returns False
        if (await self.check_game(message)):
            if not self.running:
                return True
            await message.channel.send('Cannot modify this game, it has already started.')
        return False


    def find_player(self, user):
        # Find the Player corresponding to the given user
        for player in self.players:
            if player.user == user:
                return player






    ##### Bot commands #####


    async def av_create(self, message):
        '''Create a new game'''
        # av create: creates a game
        if self.owner:
            if self.owner.user != message.author:
                await message.channel.send('A game is currently being played. Please wait for it to finish, or ask %s to cancel it.' % self.owner.user.mention)
                return
            if not (await self.askyesno('You have already created a game. Do you want to cancel it and start a new one?', message.author, message.channel)):
                return
            if self.owner:
                await self.main_channel.send('%s has canceled the currently active game.' % message.author.mention)
        self.owner = Player(message.author, (), None, None, None)
        self.running = False
        self.players = [self.owner] # List of Player objects in the game, in order
        self.team = [] # List of members of the current team
        self.leader = None
        self.quest_results = [] # Boolean values signifying which quests so far have passed
        self.reject_counter = 1 # Number of consecutive teams that have been rejected
        self.lady = None # The player who currently has the Lady of the Lake
        self.investigated = [] # Keep track of who has been investigated using Lady of the Lake
        self.waiting_for_votes = False # True if the client is waiting for people to cast their votes
        self.waiting_for_outcomes = False # True if the client is waiting for people to decide the outcome
        self.waiting_for_lady = False # True if the client is waiting for someone to play the Lady of the Lake
        self.waiting_for_assassin = False # True if the client is waiting for the assassin to kill someone
        self.has_team = False # if True, init_team() is a no-op until it is switched to False again
        self.tabulating_votes = False # True if the bot is currently tabulating voting results
        self.tabulating_outcomes = False # True if the bot is currently tabulating success/fail cards
        self.muted = False # True if the bot is currently silencing all non-bot command messages
        self.votekicks = set() # List of people who have requested that the game be canceled due to an unresponsive owner
        # Game features
        self.features = {
            # True means enabled; False disabled.
            'merlin': True,
            'morgana': False,
            'mordred': False,
            'oberon': False,
            'norebo': False,
            'palm': False,
            'lady': False,
            }
        self.merged = [] # Merged roles
        # Make a public announcement
        await self.main_channel.send('%s has just created an Avalon game. To join, simply type "av join".' % message.author.mention)
        # Ping the #off-topic channel too if it's not too soon to do that
        now = datetime.datetime.now()
        if (self.last_ping is None) or (now - self.last_ping >= self.PING_DELAY):
            if message.guild:
                role = discord.utils.get(message.guild.roles, id=self.ROLE_ID)
                self.last_ping = now
                ping_channel = discord.utils.get(self.get_all_channels(), id=self.PING_CHANNEL)
                await ping_channel.send('%s: an Avalon game has been created in %s!' % (role.mention, self.main_channel.mention))
                    
                
    async def av_cancel(self, message):
        '''Cancel a game you created'''
        # av cancel: Cancels a game. Only allowed if you created the game in the first place.
        if (await self.check_owner(message)):
            if (await self.askyesno('Are you sure you wish to cancel the currently active game?', message.author, message.channel)):
                if self.owner:
                    self.owner = None
                    # Make a public announcement
                    await self.main_channel.send('%s has canceled the currently active game.' % message.author.mention)



    async def av_join(self, message):
        '''Join a game that has not yet started'''
        # av join: Joins a game.
        if (await self.check_not_running(message)):
            # Make sure we're not already part of the game
            if self.find_player(message.author):
                await message.channel.send('You are already part of this game.')
                return
            # Add the player
            self.players.append(Player(message.author, (), None, None, None))
            # Make a public announcement
            await self.main_channel.send('%s has joined the game.' % message.author.mention)



    async def av_leave(self, message):
        '''Leave a game before it begins'''
        # av leave: Leaves a game
        if (await self.check_not_running(message)):
            # Leave is the same thing as cancel if you're the game owner
            if self.owner and (message.author == self.owner.user):
                await self.av_cancel(message)
                return
            # Make sure we're currently part of the game
            player = self.find_player(message.author)
            if not player:
                await message.channel.send('You are not part of this game.')
                return
            # Remove the player
            self.players.remove(player)
            # Make a public announcement
            await self.main_channel.send('%s has left the game.' % message.author.mention)



    async def enable(self, message, enable):
        # Internal method to enable or disable a feature
        try:
            feature = message.content.split(None, 2)[2].lower()
        except IndexError:
            # Print usage
            await message.channel.send('Syntax: av %s [feature]' % ('enable' if enable else 'disable'))
            return
        if (await self.check_not_running(message)) and (await self.check_owner(message)):
            # Make sure the feature exists
            if feature == 'all':
                # Enable/disable all
                await self.main_channel.send('all %s' % ('enabled' if enable else 'disabled'))
                for key in self.features:
                    self.features[key] = enable
                return
            if feature in ('perc', 'percival'):
                feature = 'morgana' # alias
            if feature not in self.features:
                await message.channel.send('Unrecognized feature "%s": should be one of %s, all' % (feature, ', '.join(self.features)))
                return
            await self.main_channel.send('%s %s' % (FEATURE_NAMES[feature], 'enabled' if enable else 'disabled'))
            self.features[feature] = enable



    async def av_enable(self, message):
        '''Enable a feature of the game'''
        # av enable: Enables a feature
        await self.enable(message, True)

    async def av_disable(self, message):
        '''Disable a feature of the game'''
        # av disable: Enables a feature
        await self.enable(message, False)

    

    async def av_votekick(self, message):
        '''Vote to end the game if the owner has become unresponsive'''
        # av votekick: Votes to end the game
        if (await self.check_game(message)):
            self.votekicks.add(message.author.id)
            if len(self.votekicks) == 1:
                await message.channel.send('1 person has voted to cancel the game.')
            else:
                await message.channel.send('%d people have voted to cancel the game.' % len(self.votekicks))
            if len(self.votekicks) >= 4:
                if self.owner:
                    self.owner = None
                    # Make a public announcement
                    await self.main_channel.send('The currently active game has been canceled by popular vote.')
                
            

    async def av_mute(self, message):
        '''Turn on silent mode'''
        # av mute: Blocks discussion during gameplay
        if (await self.check_not_running(message)) and (await self.check_owner(message)):
            self.muted = True
            await self.main_channel.send('**The host has muted the game.** All in-game discussion will be deleted by the bot.')

    async def av_unmute(self, message):
        '''Turn off silent mode'''
        # av unmute: Unblocks discussion during gameplay
        if (await self.check_not_running(message)) and (await self.check_owner(message)):
            self.muted = False
            await self.main_channel.send('**The host has unmuted the game.** In-game discussion is freely allowed.')



    async def av_info(self, message):
        '''Print out the current game info'''
        # av info: Prints out game info
        if (await self.check_game(message)):
            info = '**Current players:**\n%s\n' % ', '.join([player.user.name for player in self.players])
            info += 'Game owner: %s\n' % self.owner.user.mention
            if self.muted:
                info += '*This is a silent game.*\n'
            info += '**Game settings:**\n%s\n' % '\n'.join(['%s %s' % \
                                                            (FEATURE_NAMES[key], 'enabled' if value else 'disabled') \
                                                            for key, value in self.features.items()])
            if self.merged:
                info += '**Merged roles:**\n%s\n' % '\n'.join([', '.join([ROLE_NAMES[role.value] for role in group]) for group in self.merged])
            if not self.running:
                info += 'Game has not yet started.'
                await message.channel.send(info)
                return
            info += '**Current team**:\n%s\n' % ', '.join([player.user.name for player in self.team])
            info += '**Current results**:\n```\n%s\n%s\nVote tracker: %d\n```\n' % \
                    (' '.join([str(i[0]) for i in QUEST_LISTS[len(self.players)]]),
                     ' '.join(['S' if i else 'F' for i in self.quest_results]),
                     self.reject_counter)
            if self.lady:
                info += '%s currently has the Lady of the Lake' % self.lady.user.name
            if self.muted and self.running:
                await message.author.send(info)
            else:
                await message.channel.send(info)
            await self.av_poke(message)



    async def av_poke(self, message):
        '''Pokes people who need to make a decision'''
        # av poke: pings people who the game is currently waiting for to make a decision
        if (await self.check_running(message)):
            if self.waiting_for_votes:
                await message.channel.send('*Currently waiting for the following players to cast their votes: %s*' % \
                                           ', '.join([p.user.mention for p in self.players if p.vote is None]))
            elif self.waiting_for_outcomes:
                await message.channel.send('*Currently waiting for the following players to play their Success/Fail cards: %s*' % \
                                           ', '.join([p.user.mention for p in self.team if p.outcome is None]))
            elif self.waiting_for_lady:
                await message.channel.send('*Currently waiting for %s to play the Lady of the Lake*' % self.lady.user.mention)
            elif self.waiting_for_assassin:
                await message.channel.send('*Currently waiting for %s to pick someone to assassinate*' % self.assassin.user.mention)
            elif self.leader and (len(self.team) < self.current_quest[0]):
                n = self.current_quest[0] - len(self.team)
                await message.channel.send('*Currently waiting for %s to pick %d%s team member%s*' % \
                                           (self.leader.user.mention, n, (' more' if self.team else ''), ('s' if n > 1 else '')))
            else:
                await message.channel.send('*Not currently waiting for anyone to make a decision.*')




    async def av_merge(self, message):
        '''Merge two special roles'''
        # av merge: merge two or more roles
        roles = message.content.split()[2:]
        if len(roles) < 2:
            # Print usage
            await message.channel.send('Syntax: av merge [role1 role2 ...]')
            return
        if (await self.check_not_running(message)) and (await self.check_owner(message)):
            values = []
            # Look up the roles based on the string
            for role in roles:
                try:
                    value = ROLE_NAMES[3:].index(role.title()) + 3
                except ValueError:
                    # Role does not exist
                    await message.channel.send('Unrecognized role "%s": should be one of %s' % (role, ', '.join(ROLE_NAMES[3:])))
                    return
                else:
                    if Role(value) in values:
                        await message.channel.send('Duplicate role "%s"' % role)
                        return
                    values.append(Role(value))
            # Find everything else that overlaps and merge it into one
            for merge in self.merged[:]:
                if set(merge).intersect(values):
                    values.extend(merge)
                    self.merged.remove(merge)
            values = sorted(set(values), key = lambda x: x.value)
            # Make sure the merged roles are actually okay to merge
            # First check that they are either all good or all evil
            good = [value for value in values if value in GOOD_ROLES]
            if len(good) not in (0, len(values)):
                await message.channel.send('Cannot merge good roles with evil roles.')
                return
            if (Role.MERLIN in values) and (Role.PERCIVAL in values):
                await message.channel.send('Cannot merge Merlin with Percival.') # This would break too many things
                return
            self.merged.append(values)
            # Enable things if necessary
            for role in values:
                name = ROLE_NAMES[role.value].lower()
                if name == 'assassin': name = 'merlin'
                if name == 'percival': name = 'morgana'
                if not self.features[name]:
                    self.features[name] = True
                    await message.channel.send('%s enabled' % FEATURE_NAMES[name])
            # Make a public announcement
            await self.main_channel.send('Roles %s have been merged for this game.' % ', '.join([ROLE_NAMES[role.value] for role in values]))




    async def av_unmerge(self, message):
        '''Unmerge all previously merged special roles'''
        # av unmerge: unmerge all roles
        if (await self.check_not_running(message)) and (await self.check_owner(message)):
            self.merged = []
            await self.main_channel.send('All roles have been unmerged for this game.')




    async def av_start(self, message):
        '''Start the game that was previously created'''
        # av start: starts the game
        if (await self.check_owner(message)):
            if self.running:
                await message.channel.send('The game has already started.')
                return
            # Set up the quests
            try:
                self.quests = iter(QUEST_LISTS[len(self.players)])
            except KeyError:
                await message.channel.send('Cannot start: this game has too %s players' % ('few' if len(self.players) < 5 else 'many'))
                return
            self.current_quest = next(self.quests) # This is always a 2-tuple (team members, fails required)
            self.running = True
            # Make a public announcement
            await self.main_channel.send('The game has now been started!')
            # Set up the game
            random.seed() # Seed the random number generator
            random.shuffle(self.players) # Randomize the play order
            if self.features['lady']:
                self.lady = self.players[-1] # Give the Lady of the Lake to the last player who will get to lead a team
                self.investigated = [self.lady]
            await self.av_info(message) # Print out the public info
            await self.secret_info()
            await self.init_team()



    async def pick(self, message, *users):
        # Internal method to add people to the team
        if (await self.check_running(message)):
            if message.author != self.leader.user:
                await message.channel.send('Error: You are not currently the leader of the team.')
                return
            if len(self.team) == self.current_quest[0]:
                await message.channel.send('Error: Your team is currently full.')
                return
            new_players = []
            for user in users:
                player = self.find_player(user)
                if not player:
                    await message.channel.send('Error: %s is not part of the game.' % user.name)
                    return
                if player in self.team + new_players:
                    await message.channel.send('Error: %s is already part of the team.' % player.user.name)
                    return
                new_players.append(player)
                if len(self.team + new_players) > self.current_quest[0]:
                    await message.channel.send('Error: the team only has room for %d members.' % self.current_quest[0])
                    return
            # Add the new players then
            self.team.extend(new_players)
            # Make a public announcement:
            await self.main_channel.send('%s added new teammate%s %s.' % (self.leader.user.mention,
                                                                          's' if len(new_players) >= 2 else '',
                                                                          ', '.join([player.user.mention for player in new_players])))
            # Figure out if we now have the correct number
            if len(self.team) == self.current_quest[0]:
                await self.init_voting()
            else:
                n = self.current_quest[0] - len(self.team)
                await message.channel.send('You still need to pick %d more teammate%s.' % (n, 's' if n >= 2 else ''))



    async def av_pick(self, message):
        '''Pick someone as a member of your team (note there is no way to "un-pick" them later!)'''
        # av pick: Pick people to join your team
        if not message.mentions:
            # Print usage
            await message.channel.send('Syntax: av pick [mention teammates]')
            return
        await self.pick(message, *message.mentions)

    async def av_pickme(self, message):
        '''Shortcut to pick yourself for your own team'''
        # av pickme: Pick yourself to join your team
        await self.pick(message, message.author)

    async def av_pickrandom(self, message):
        '''Pick a random person to join your team'''
        # av pickrandom: Pick a random person to join your team
        if (await self.check_running(message)):
            await self.pick(message, random.choice([p for p in self.players if p not in self.team]).user)



    async def vote(self, message, vote):
        # Internal method to vote for or against a team
        if (await self.check_running(message)):
            if message.channel.type != discord.ChannelType.private:
                await message.delete()
                await message.channel.send('Votes should be cast in a **private message** to %s. Please try again.' % self.user.mention)
                return
            if len(self.team) != self.current_quest[0]:
                await message.channel.send('Cannot vote: the team is not full yet.')
                return
            player = self.find_player(message.author)
            if player is None:
                await message.channel.send('Cannot vote: you are not part of this game.')
                return
            if not self.waiting_for_votes:
                await message.channel.send('Sorry, it is too late to change your vote.')
                return
            if player.vote is None:
                await message.channel.send('Thank you for voting!')
            else:
                await message.channel.send('Your vote has been updated.')
            player.vote = vote
            if not any([p.vote is None for p in self.players]):
                # Only do this *once*!
                if not self.tabulating_votes:
                    self.tabulating_votes = True
                else:
                    return
                approved = (await self.tabulate_votes())
                if self.running:
                    if approved:
                        await self.init_outcome()
                    else:
                        self.has_team = False
                        await self.init_team()
                # Reset the votes to make extra sure
                for player in self.players:
                    player.vote = None
                self.tabulating_votes = False



    async def av_approve(self, message):
        '''Vote yes to a proposed team'''
        # av approve: Signal that you approve of the proposed team.
        await self.vote(message, APPROVE)

    async def av_reject(self, message):
        '''Vote no to a proposed team'''
        # av reject: Signal that you disapprove of the proposed team.
        await self.vote(message, REJECT)



    async def outcome(self, message, outcome):
        # Internal method to signal a quest to succeed or fail
        if (await self.check_running(message)):
            if message.channel.type != discord.ChannelType.private:
                await message.delete()
                await message.channel.send('Play your success or fail cards in a **private message** to %s, you doofus.' % self.user.mention)
                return
            if not self.waiting_for_outcomes:
                await message.channel.send('Too early to play success or fail cards.')
                return
            player = self.find_player(message.author)
            if player is None:
                await message.channel.send('Cannot play success/fail cards: you are not part of this game.')
                return
            if player not in self.team:
                await message.channel.send('Cannot play success/fail cards: you are not part of this team.')
                return
            if player.outcome is not None:
                await message.channel.send('You have already played a success/fail card.')
                return
            if (player.side == GOOD) and (outcome == FAIL):
                await message.channel.send('Servants of Arthur are not permitted to play Fail cards. Please use the "av success" command.')
                return
            player.outcome = outcome
            await message.channel.send('Thank you for playing your card!')
            if self.team and not any([p.outcome is None for p in self.team]):
                # Only do this *once*!
                if not self.tabulating_outcomes:
                    self.tabulating_outcomes = True
                else:
                    return
                if self.waiting_for_lady:
                    return
                await self.tabulate_outcome()
                if self.running and not self.waiting_for_assassin:
                    if self.lady and (len(self.quest_results) >= 2):
                        self.waiting_for_lady = True
                        await self.main_channel.send('**Lady of the Lake:** %s, choose someone to investigate using "av lady".' % self.lady.user.mention)
                    else:
                        self.current_quest = next(self.quests)
                        self.has_team = False
                        await self.init_team()
                # Reset the outcomes to make extra sure
                for player in self.players:
                    player.outcome = None
                self.tabulating_outcomes = False



    async def av_success(self, message):
        '''Signal that a quest should succeed'''
        # av success: Signal that a quest should succeed.
        await self.outcome(message, SUCCESS)

    async def av_fail(self, message):
        '''Cause a quest to fail'''
        # av fail: Signal that a quest should fail.
        await self.outcome(message, FAIL)



    async def av_lady(self, message):
        '''Investigate the alignment of another player using Lady of the Lake'''
        # av lady: Pick someone to investigate.
        if len(message.mentions) != 1:
            # Print usage
            await message.channel.send('Syntax: av lady [mention target]')
            return
        if (await self.check_running(message)):
            if not self.waiting_for_lady:
                await message.channel.send('Error: It is not currently time to use the Lady of the Lake.')
                return
            if message.author != self.lady.user:
                await message.channel.send('Error: You do not currently have the Lady of the Lake.')
                return
            target = message.mentions[0]
            player = self.find_player(target)
            if not player:
                await message.channel.send('Error: %s is not part of the game.' % target.name)
                return
            if player.user == message.author:
                await message.channel.send('Error: you cannot investigate yourself.')
                return
            if player in self.investigated:
                await message.channel.send('Error: you cannot investigate someone who has already had the Lady of the Lake.')
                return
            # Make a public announcement
            await self.main_channel.send('**Lady of the Lake:** %s has chosen to investigate %s.' % (self.lady.user.mention, player.user.mention))
            # Send a private message
            await self.lady.user.send('Investigative result: %s is **%s**' % (player.user.name, 'Good' if player.side == GOOD else 'Evil'))
            # And update who has the Lady of the Lake
            self.lady = player
            self.waiting_for_lady = False
            self.current_quest = next(self.quests)
            self.has_team = False
            await self.init_team()
            


    async def av_assassinate(self, message):
        '''Try to kill Merlin (if you are the Assassin and it is the end of the game)'''
        # av assassinate: Pick someone to assassinate.
        if len(message.mentions) != 1:
            # Print usage
            await message.channel.send('Syntax: av assassinate [mention victim]')
            return
        if (await self.check_running(message)):
            if not self.waiting_for_assassin:
                await message.channel.send('Error: It is not currently time to assassinate someone.')
                return
            if message.author != self.assassin.user:
                await message.channel.send('Error: You are not the Assassin.')
                return
            target = message.mentions[0]
            player = self.find_player(target)
            if not player:
                await message.channel.send('Error: %s is not part of the game.' % target.name)
                return
            # Make a public announcement
            await self.main_channel.send('**Assassin:** %s has chosen to assassinate %s.' % (self.assassin.user.mention, player.user.mention))
            async with self.main_channel.typing():
                await asyncio.sleep(5) # Pause for dramatic effect
            if Role.MERLIN in player.role:
                await message.channel.send('**The game is over. %s correctly identified Merlin. Evil wins!!**' % self.assassin.user.mention)
                await self.finish_game(EVIL)
            else:
                await message.channel.send('**The game is over. %s failed to identify Merlin. Good wins!!**' % self.assassin.user.mention)
                await self.finish_game(GOOD)
            



    async def av_roles(self, message):
        '''Print out info about the gameplay roles'''
        # av characters: DMs character info
        await message.author.send('''**Avalon character roles:**

Merlin - a Servant of Arthur who knows all the Minions of Mordred
Percival - a Servant of Arthur who knows the identity of Merlin
Morgana - a Minion of Mordred who looks like Merlin to Percival
Mordred - a Minion of Mordred invisible to Merlin
Oberon - a Minion of Mordred invisible to the other Minions of Mordred but visible to Merlin
Norebo - a Servant of Arthur who looks like a Minion of Mordred to the other Minions of Mordred
Palm - a Servant of Arthur who looks like a Minion of Mordred to Merlin and to the other Minions of Mordred

Lady of the Lake - a card used to learn the alignment of another player''')



    async def av_rules(self, message):
        '''Gives link to the game rulebook'''
        # av rules: Posts link to game rules
        await message.channel.send('http://upload.snakesandlattes.com/rules/r/ResistanceAvalon.pdf')

    async def av_ping(self, message):
        '''Ping the Avalon bot'''
        # av ping: Ping the Avalon bot
        await message.channel.send('pong')

    async def av_coin(self, message):
        '''Simulate a random coin flip'''
        # av coin: Simulate a random coin flip
        await message.channel.send(random.choice(['heads', 'tails']))





    async def fetch_stats(self):
        self.fetching_stats = True
        # First load the stats if they exist
        try:
            with open('avalon_stats', 'rb') as o:
                stats = pickle.load(o)
            last_update = stats[-1][-1]
        except IOError:
            stats = []
            last_update = None
        # `stats` is a list of tuples of the form (user_id, role_id, win_bool, merge_count, timestamp)
        # in chronological order
        # First, update the stats so they're current
        good_won = None
        async for msg in self.main_channel.history(after=last_update, oldest_first=True, limit=None):
            if msg.author == self.user:
                # Check for a victory announcement.
                # Going from oldest to newest means this should be made
                # right before role reveals
                if 'Good wins!!' in msg.content:
                    good_won = True
                elif 'Evil wins!!' in msg.content:
                    good_won = False
                # Scan message for role reveals.
                timestamp = msg.created_at
                for match in STATS_RE.finditer(msg.content):
                    user_id = int(match.group(1))
                    role_names = match.group(2)
                    merge_count = role_names.count('/') + 1
                    for role_name in role_names.split('/'):
                        role_id = ROLE_NAMES.index(role_name)
                        good_role = (Role(role_id) in GOOD_ROLES)
                        win_bool = (good_won == good_role)
                        stats.append((user_id, role_id, win_bool, merge_count, timestamp))
        # Then save them back to the file
        with open('avalon_stats', 'wb') as o:
            pickle.dump(stats, o)
        self.fetching_stats = False
        return stats



    async def av_stats(self, message):
        '''Print out the player stats'''
        # av stats: Print out the player stats
        if self.muted and self.running:
            channel = message.author
        else:
            channel = message.channel
        if self.fetching_stats:
            await channel.send('*The bot is currently busy fetching stats.*')
            return
        async with channel.typing():
            stats = (await self.fetch_stats())
            # Parse the query the user has made
            content_iter = iter(message.content.split()[2:])
            user_id = None
            role_id = None
            before_ts = None
            after_ts = None
            for string in content_iter:
                string = string.lower()
                m = MENTION_RE.match(string)
                if m:
                    # First case: the string is a mention
                    if user_id:
                        await channel.send('Error: Duplicate user name given in stats request')
                        return
                    user_id = int(m.group(1))
                    continue
                # Role aliases
                if string == 'perc':
                    string = 'percival'
                if string == 'loyal':
                    string = 'servant'
                if string in ROLE_COMMANDS[1:]:
                    # Second case: the string is a role name
                    if role_id:
                        await channel.send('Error: Duplicate role name given in stats request')
                        return
                    role_id = int(ROLE_COMMANDS.index(string))
                    continue
                if string == 'before':
                    # Third case: the string indicates that a "before" date should be parsed next
                    if before_ts:
                        await channel.send('Error: Duplicate timestamp given in stats request')
                        return
                    try:
                        ts = next(content_iter)
                    except StopIteration:
                        await channel.send('Error: Truncated timestamp given in stats request')
                        return
                    try:
                        before_ts = datetime.datetime.strptime(ts, '%m/%d/%Y') + datetime.timedelta(days=1)
                    except ValueError:
                        await channel.send('Error: Invalid timestamp; should be given in format mm/dd/yyyy')
                        return
                    continue
                if string == 'after':
                    # Fourth case: the string indicates that an "after" date should be parsed next
                    if after_ts:
                        await channel.send('Error: Duplicate timestamp given in stats request')
                        return
                    try:
                        ts = next(content_iter)
                    except StopIteration:
                        await channel.send('Error: Truncated timestamp given in stats request')
                        return
                    try:
                        after_ts = datetime.datetime.strptime(ts, '%m/%d/%Y')
                    except ValueError:
                        await channel.send('Error: Invalid timestamp; should be given in format mm/dd/yyyy')
                        return
                    continue
                try:
                    dt = datetime.datetime.strptime(string, '%b')
                except ValueError:
                    try:
                        dt = datetime.datetime.strptime(string, '%B')
                    except ValueError:
                        dt = None
                if dt:
                    # Fifth case: the string indicates a month during which stats should be gathered
                    now = datetime.datetime.utcnow()
                    if before_ts or after_ts:
                        await channel.send('Error: Duplicate timestamp given in stats request')
                        return
                    if dt.month > now.month:
                        year = now.year - 1
                    else:
                        year = now.year
                    after_ts = datetime.datetime(year, dt.month, 1)
                    if dt.month == 12:
                        before_ts = datetime.datetime(year+1, 1, 1)
                    else:
                        before_ts = datetime.datetime(year, dt.month+1, 1)
                    continue
                if string == 'help':
                    # Sixth case: the user wants help using the stats command
                    await channel.send('''Specifiers that can be given in an `av stats` invocation include:
 - The mention, username, or nickname of a Discord user
 - The name of a role (%s)
 - The word "good" or "evil"
 - The name of a month to restrict stats to
 - A string of the form "before mm/dd/yyyy" or "after mm/dd/yyyy" to restrict stats to a certain range of dates (both may be specified) 
 - The word "help" to print out this message
 ''' % ', '.join(ROLE_COMMANDS[1:]))
                    return
                if string == 'bad':
                    string = 'evil' # Synonyms
                if string in ('good', 'evil'):
                    # Seventh case: the string is the "good" or "evil" side
                    if role_id:
                        await channel.send('Error: Duplicate role name given in stats request')
                        return
                    role_id = string
                    continue
                if string == 'heff':
                    string = 'heff10' # Expected behavior :P
                for member in self.get_all_members():
                    # Eighth case: the string is a username or nickname of someone on the channel (but not a mention)
                    if (member.name.lower() == string) or (member.nick and (member.nick.lower() == string)):
                        if user_id:
                            await channel.send('Error: Duplicate user name given in stats request')
                            return
                        user_id = member.id
                        break
                else:
                    # Fail message
                    await channel.send('Error: unparseable token "%s" given in stats request' % string)
                    return
            # Put together the statistical data to be printed
            if user_id:
                stats = [i for i in stats if i[0] == user_id]
            if role_id == 'good':
                stats = [i for i in stats if Role(i[1]) in GOOD_ROLES]
            elif role_id == 'evil':
                stats = [i for i in stats if Role(i[1]) in EVIL_ROLES]
            elif role_id:
                stats = [i for i in stats if i[1] == role_id]
            if before_ts:
                stats = [i for i in stats if i[4] < before_ts]
            if after_ts:
                stats = [i for i in stats if i[4] >= after_ts]
            if not stats:
                await channel.send('No statistical data exists matching this query.')
                return
            # Create the rows of data
            rows = []
            if user_id:
                # If a specific user is given, print out their role info
                counter = {}
                total = [0, 0]
                for user, role, win_bool, merge_count, timestamp in stats:
                    data = counter.setdefault(role, [0, 0])
                    if win_bool:
                        data[0] += 1
                        total[0] += 1.0 / merge_count
                    else:
                        data[1] += 1
                        total[1] += 1.0 / merge_count
                header_row = ('Role', 'Wins', 'Losses', 'Total', 'Win Ratio')
                rows = [(ROLE_NAMES[key], str(w), str(l), str(w+l), '%.4g%%' % (100*w/(w+l))) for key, (w, l) in counter.items()]
                total_row = ('Total', str(int(total[0])), str(int(total[1])), str(int(total[0]+total[1])), '%.4g%%' % (100*total[0]/(total[0]+total[1])))
                rows.sort(key = lambda x: float(x[-1][:-1]), reverse=True)
                rows.insert(0, header_row)
                if len(rows) > 2:
                    rows.append(total_row)
            else:
                # Print out info sorted by users then
                counter = {}
                for user, role, win_bool, merge_count, timestamp in stats:
                    data = counter.setdefault(user, [0, 0])
                    if win_bool:
                        data[0] += (1 if isinstance(role_id, int) else 1.0 / merge_count)
                    else:
                        data[1] += (1 if isinstance(role_id, int) else 1.0 / merge_count)
                header_row = ('Player', 'Wins', 'Losses', 'Total', 'Win Ratio')
                rows = [(discord.utils.get(self.get_all_members(), id=key).name, str(int(w)), str(int(l)), str(int(w+l)), '%.4g%%' % (100*w/(w+l))) for key, (w, l) in counter.items()]
                rows.sort(key = lambda x: float(x[-1][:-1]), reverse=True)
                rows.insert(0, header_row)
            # Create the aligned table message
            lengths = [max([len(row[i]) for row in rows]) for i in range(5)]
            divider = '+%s+\n' % '+'.join(['-'*l for l in lengths])
            rows = ['|%s|\n' % '|'.join([entry.rjust(l) for entry, l in zip(row, lengths)]) for row in rows]
            table = divider + divider.join(rows) + divider
            # Generate the descriptive message at the top
            description = 'Avalon player stats'
            if user_id:
                description += ' for %s' % discord.utils.get(self.get_all_members(), id=user_id).mention
            if role_id == 'good':
                description += ' for Good'
            elif role_id == 'evil':
                description += ' for Evil'
            elif role_id:
                description += ' for %s' % ROLE_NAMES[role_id]
            if before_ts:
                before_ts -= datetime.timedelta(days=1)
            if before_ts and after_ts:
                description += ' between %s and %s' % (after_ts.strftime('%x'), before_ts.strftime('%x'))
            elif before_ts:
                description += ' before %s' % before_ts.strftime('%x')
            elif after_ts:
                description += ' after %s' % after_ts.strftime('%x')
            # Print out the whole table
            await channel.send('**%s:**\n```\n%s```' % (description, table))
                




            
        
                


    async def av_help(self, message):
        '''I'm guessing you've figured out by now what this one does'''
        # av help: DMs list of commands
        await message.author.send(self.help)



    async def av_debug(self, message):
        # av debug: For debugging only!!
        if message.author.id != 452938434055503892:
            await message.channel.send('You do not have permission to run debugging commands!')
            return
        start = message.content.find('```')
        if start == -1:
            await message.channel.send('Syntax: av debug ```[code]```')
            return
        start += 3
        end = message.content.find('```', start)
        if end == -1:
            await message.channel.send('Syntax: av debug ```[code]```')
            return
        code = message.content[start:end]
        outp = io.StringIO()
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        sys.stdout = sys.stderr = outp
        try:
            exec(code)
        except:
            traceback.print_exc()
        sys.stdout = old_stdout
        sys.stderr = old_stderr
        s = outp.getvalue()
        if s:
            await message.channel.send('```%s```' % s)



    async def av_heff(self, message):
        # av heff: self explanatory
        if message.channel_mentions:
            heff = message.channel_mentions[0]
        else:
            heff = discord.utils.get(self.get_all_members(), id=330785420914851840)
        await heff.send('shup heff')



    async def av_spotify(self, message):
        # av spotify: Turn on the secret true randomness feature
        await message.channel.send('Spotify mode on')
        self.spotify_mode = True

    async def av_unspotify(self, message):
        # av unspotify: Turn off the secret true randomness feature
        # and use normal, boring randomness instead.
        await message.channel.send('Spotify mode off')
        self.spotify_mode = False





    # Synonyms (by popular demand)
    av_new = av_create
    av_quit = av_stop = av_end = av_cancel
    av_in = av_enter = av_join
    av_out = av_exit = av_leave
    av_prod = av_poke
    av_begin = av_start
    av_choose = av_add = av_picc = av_pick
    av_rand = av_random = av_pickrandom
    av_accept = av_yes = av_yee = av_ok = av_okay = av_aight = av_yep = av_yeet = av_approve
    av_no = av_nope = av_noway = av_rejecc = av_reject
    av_succ = av_success
    av_sab = av_sabotage = av_fail
    av_investigate = av_lady
    av_shoot = av_kill = av_assassinate
    av_characters = av_chars = av_roles
    av_coinflip = av_coin
        
        





    ##### Other game running methods #####


    async def secret_info(self):
        # Figure out which roles are being used
        n_evil = N_EVIL[len(self.players)]
        good = [Role.SERVANT for i in range(len(self.players) - n_evil)]
        evil = [Role.MINION for i in range(n_evil)]
        special_good = []
        special_evil = []
        # Merlin/Morgana roles
        if self.features['merlin']:
            special_good.append(Role.MERLIN)
            special_evil.append(Role.ASSASSIN)
            if self.features['morgana']:
                special_good.append(Role.PERCIVAL)
                special_evil.append(Role.MORGANA)
        elif self.features['morgana']:
            # Warn that these are being ignored
            await self.main_channel.send('Switching Morgana/Percival off because Merlin is off.')
            self.features['morgana'] = False
        # Other weird roles
        if self.features['mordred']:
            special_evil.append(Role.MORDRED)
        if self.features['oberon']:
            special_evil.append(Role.OBERON)
        if self.features['norebo']:
            special_good.append(Role.NOREBO)
        if self.features['palm']:
            special_good.append(Role.PALM)
        # Merged roles
        for merge in self.merged:
            good_merge = tuple([role for role in merge if role in special_good])
            evil_merge = tuple([role for role in merge if role in special_evil])
            if len(good_merge) >= 2:
                for role in good_merge:
                    special_good.remove(role)
                special_good.append(good_merge)
            elif len(evil_merge) >= 2:
                for role in evil_merge:
                    special_evil.remove(role)
                special_evil.append(evil_merge)
        # Consolidate all roles into the appropriately sized lists
        good = (special_good + good)[:len(good)]
        evil = (special_evil + evil)[:len(evil)]
        # Turn off roles if we don't have enough players for them
        rejected_roles = [role for role in special_good if role not in good] + \
                         [role for role in special_evil if role not in evil]
        for role in rejected_roles:
            if not isinstance(role, tuple):
                role = (role,)
            await self.main_channel.send('Switching %s off because there are not enough players.' % '/'.join([ROLE_NAMES[r.value] for r in role]))
            for sub in role:
                feature = ROLE_NAMES[sub.value].lower()
                if feature in self.features:
                    self.features[feature] = False
        # Randomly assign them to players
        roles = [(role, True) for role in good] + [(role, False) for role in evil]
        if self.spotify:
            roles = (await self.spotify_shuffle(roles))
        else:
            random.shuffle(roles)
        for player, (role, side) in zip(self.players, roles):
            player.role = (role if isinstance(role, tuple) else (role,))
            player.side = side
            names = [ROLE_NAMES[role.value] for role in player.role]
            names = [name for name in names if name not in ('Palm', 'Norebo')] # Palm and Norebo don't know their own identities.
            name = '/'.join(names) or ROLE_NAMES[Role.SERVANT.value] # `names` should only be empty if it's a good guy whose special role is Palm or Norebo
            await player.user.send('Your role for this game: **%s**\nYour alignment: **%s**' % \
                                   (name, ('Good' if side == GOOD else 'Evil')))
        # Disclose information to players as appropriate
        for player in self.players:
            # Bad guys figure out who each other are (save for Oberon)
            # There may be impostors in this list if Norebo and/or Palm are in play.
            if (player.side == EVIL) and (Role.OBERON not in player.role):
                other_minions = [p.user.name for p in self.players if (p != player) and (((p.side == EVIL) and (Role.OBERON not in p.role)) \
                                 or (Role.NOREBO in p.role) or (Role.PALM in p.role))]
                if other_minions:
                    await player.user.send('Other Minions of Mordred: %s' % ', '.join(other_minions))
                else:
                    await player.user.send('There are no other Minions of Mordred.')
            # Merlin knows who the bad guys are (save for Mordred)
            # If Palm is in play Merlin will think he's bad too.
            elif Role.MERLIN in player.role:
                minions = [p.user.name for p in self.players if ((Role.MORDRED not in p.role) and (p.side == EVIL)) or (Role.PALM in p.role)]
                if minions:
                    await player.user.send('The Minions of Mordred are: %s' % ', '.join(minions))
                else:
                    await player.user.send('There are no Minions of Mordred.')
            # Percival knows who Morgana and Merlin are (but not which is which)
            elif Role.PERCIVAL in player.role:
                merlins = [p.user.name for p in self.players if (Role.MERLIN in p.role) or (Role.MORGANA in p.role)]
                random.shuffle(merlins)
                await player.user.send('Merlin and Morgana are %s and %s (in some order)' % tuple(merlins))
                

        


    async def init_team(self):
        # Announce a new leader and let them pick a team
        if self.has_team:
            return # Shouldn't happen (but does... ugh)
        self.has_team = True
        if self.leader:
            index = self.players.index(self.leader)
            self.leader = self.players[(index + 1) % len(self.players)]
        else:
            self.leader = self.players[0]
        self.team = []
        await self.main_channel.send('%s is now the leader. Pick %d people to join the team (possibly including yourself) using "av pick".' % \
                                     (self.leader.user.mention, self.current_quest[0]))
        # Special messages if necessary
        if self.current_quest[1] == 2:
            await self.main_channel.send('**Reminder: This quest requires 2 fails instead of 1.**')
        if self.reject_counter == 4:
            await self.main_channel.send('**Warning: Evil will win if this quest is rejected.**')



    async def init_voting(self):
        # Reset everyone's votes and let them cast votes again
        if not self.waiting_for_votes:
            self.waiting_for_votes = True
            for player in self.players:
                player.vote = None
            await self.main_channel.send('''Everyone: the team for this quest is %s.
Please cast your votes **privately** by DMing either "av approve" or "av reject" to %s.''' % \
                                         (', '.join([player.user.mention for player in self.team]), self.user.mention))


    async def tabulate_votes(self):
        # Tabulate the votes that were cast
        if self.waiting_for_votes:
            self.waiting_for_votes = False
            voting_msg = (await self.main_channel.send('Voting for the team has concluded. Results are:\n%s' % \
                                                       '\n'.join(['%s: %s' % (p.user.name, 'Approve' if p.vote == APPROVE else 'Reject') for p in self.players])))
            await voting_msg.delete(delay=self.VOTE_DELAY) # Delete after a certain time
            if sum([p.vote for p in self.players]) > len(self.players) // 2:
                await self.main_channel.send('The team consisting of %s was approved!' % ', '.join([player.user.mention for player in self.team]))
                self.reject_counter = 1
                return True
            self.reject_counter += 1
            await self.main_channel.send('The team consisting of %s was rejected. Vote tracker is now at **%d** out of 5.' % \
                                         (', '.join([player.user.mention for player in self.team]), self.reject_counter))
            await self.check_for_winner()
        return False



    async def init_outcome(self):
        # Let everyone on the team play success/fail cards
        if not self.waiting_for_outcomes:
            self.waiting_for_outcomes = True
            for player in self.team:
                player.outcome = None
            await self.main_channel.send('''Everyone who is on the team: please signal the outcome of this quest
**privately** by DMing either "av success" or "av fail" to %s.''' % self.user.mention)


    async def tabulate_outcome(self):
        # Determine whether the quest succeeded
        if self.waiting_for_outcomes:
            self.waiting_for_outcomes = False
            async with self.main_channel.typing():
                await asyncio.sleep(5) # Pause for dramatic effect
            n_fails = [p.outcome for p in self.team].count(FAIL)
            if n_fails == 1:
                await self.main_channel.send('There was 1 Fail card played out of %d.' % len(self.team))
            else:
                await self.main_channel.send('There were %d Fail cards played out of %d.' % (n_fails, len(self.team)))
            if n_fails >= self.current_quest[1]:
                await self.main_channel.send('**The quest has failed.**')
                self.quest_results.append(False)
            else:
                await self.main_channel.send('**The quest has succeeded!**')
                self.quest_results.append(True)
            await self.check_for_winner()



    async def check_for_winner(self):
        # Check for a winner
        if self.quest_results.count(False) >= 3:
            await self.main_channel.send('**The game is over. Evil wins!!**')
            await self.finish_game(EVIL)
        elif self.reject_counter >= 5:
            await self.main_channel.send('**The game is over. The vote tracker has reached 5. Evil wins!!**')
            await self.finish_game(EVIL)
        elif self.quest_results.count(True) >= 3:
            if self.features['merlin']:
                self.assassin = [p for p in self.players if Role.ASSASSIN in p.role][0]
                self.waiting_for_assassin = True
                await self.main_channel.send('**Good is about to win.** %s, choose someone to assassinate using "av assassinate".' % self.assassin.user.mention)
            else:
                await self.main_channel.send('**The game is over. Good wins!!**')
                await self.finish_game(GOOD)


    async def finish_game(self, winner):
        # Announce the roles and clear the `running' flag
        self.owner = None
        self.running = False
        info = '**Game role reveals:**\n'
        for p in self.players:
            info += '%s: %s\n' % (p.user.mention, '/'.join([ROLE_NAMES[role.value] for role in p.role]))
        await self.main_channel.send(info)




    async def spotify_shuffle(self, roles):
        # Implements TRUE randomness
        roles = [i if isinstance(i, tuple) else (i,) for i in roles]
        sample = list(itertools.permutations(roles))
        if len(sample) > 500:
            sample = random.sample(sample, 500)
        stats = (await self.fetch_stats())
        ids = [p.user.id for p in self.players]
        count = 0
        for user_id, role_id, win_bool, merge_count, timestamp in stats[::-1]:
            count += 1
            role = Role(role_id)
            if user_id in ids:
                index = ids.index(user_id)
                newsample = []
                # When building the new, reduced, sample of permutations to choose
                # from, make sure that the player indicated by user_id did not have
                # the same role in this recent game as they do now
                for perm in sample:
                    if role not in perm[index]:
                        newsample.append(perm)
                if not newsample:
                    # Have to finish now
                    return list(random.choice(sample))
                # Otherwise loop back again
                sample = newsample
                if count == 100:
                    return list(random.choice(sample))
        # If we make it all the way to the end, just do a random permutation from
        # the remaining choices
        return list(random.choice(sample))
        
        
                
        
            
        
        





if __name__ == '__main__':
    client = Avalon()
    client.run(client.TOKEN)
