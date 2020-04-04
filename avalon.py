# Avalon discord bot
# Matthew Kroesche

import discord
import recordclass
import enum
import sys
import io
import pickle
import traceback
import random
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


    def __init__(self):
        discord.Client.__init__(self)
        self.main_channel = None # The default channel to post messages in
        self.owner = None # The player who started the game
        self.running = False # True if the game is currently ongoing


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
        command = 'av_' + message.content.split(None, 2)[1].lower()
        if hasattr(self, command):
            await getattr(self, command)(message)




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
                    
                
    async def av_cancel(self, message):
        # av cancel: Cancels a game. Only allowed if you created the game in the first place.
        if (await self.check_owner(message)):
            if (await self.askyesno('Are you sure you wish to cancel the currently active game?', message.author, message.channel)):
                if self.owner:
                    self.owner = None
                    # Make a public announcement
                    await self.main_channel.send('%s has canceled the currently active game.' % message.author.mention)



    async def av_join(self, message):
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
                for key in self.features:
                    self.features[key] = enable
            if feature not in self.features:
                await message.channel.send('Unrecognized feature "%s": should be one of %s, all' % (feature, ', '.join(self.features)))
                return
            await message.channel.send('%s %s' % (FEATURE_NAMES[feature], 'enabled' if enable else 'disabled'))
            self.features[feature] = enable



    async def av_enable(self, message):
        # av enable: Enables a feature
        await self.enable(message, True)

    async def av_disable(self, message):
        # av disable: Enables a feature
        await self.enable(message, False)



    async def av_info(self, message):
        # av info: Prints out game info
        if (await self.check_game(message)):
            info = '**Current players:**\n%s\n' % ', '.join([player.user.name for player in self.players])
            info += '**Game settings:**\n%s\n' % '\n'.join(['%s %s' % \
                                                            (FEATURE_NAMES[key], 'enabled' if value else 'disabled') \
                                                            for key, value in self.features.items()])
            if self.merged:
                info += '**Merged roles:**:\n%s\n' % '\n'.join([', '.join([ROLE_NAMES[role.value] for role in group]) for group in self.merged])
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
            await message.channel.send(info)
            await self.av_poke(message)



    async def av_poke(self, message):
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
                await message.channel.send('*Currently waiting for %s to pick %d %s team member%s*' % \
                                           (self.leader.user.mention, n, ('more' if self.team else ''), ('s' if n > 1 else '')))
            else:
                await message.channel.send('*Not currently waiting for anyone to make a decision.*')




    async def av_merge(self, message):
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
        # av unmerge: unmerge all roles
        if (await self.check_not_running(message)) and (await self.check_owner(message)):
            self.merged = []
            await self.main_channel.send('All roles have been unmerged for this game.')




    async def av_start(self, message):          
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
            await message.channel.send('%s added new teammate%s %s.' % (self.leader.user.mention,
                                                                        's' if len(new_players) >= 2 else '',
                                                                        ', '.join([player.user.mention for player in new_players])))
            # Figure out if we now have the correct number
            if len(self.team) == self.current_quest[0]:
                await self.init_voting()
            else:
                n = self.current_quest[0] - len(self.team)
                await message.channel.send('You still need to pick %d more teammate%s.' % (n, 's' if n >= 2 else ''))



    async def av_pick(self, message):
        # av pick: Pick people to join your team
        if not message.mentions:
            # Print usage
            await message.channel.send('Syntax: av pick [mention teammates]')
            return
        await self.pick(message, *message.mentions)

    async def av_pickme(self, message):
        # av pickme: Pick yourself to join your team
        await self.pick(message, message.author)

    async def av_pickrandom(self, message):
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
        # av approve: Signal that you approve of the proposed team.
        await self.vote(message, APPROVE)

    async def av_reject(self, message):
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
        # av success: Signal that a quest should succeed.
        await self.outcome(message, SUCCESS)

    async def av_fail(self, message):
        # av fail: Signal that a quest should fail.
        await self.outcome(message, FAIL)



    async def av_lady(self, message):
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
                await message.channel.send('Error: %s is not part of the game.' % player.user.name)
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
                await message.channel.send('Error: %s is not part of the game.' % player.user.name)
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
        # av rules: Posts link to game rules
        await message.channel.send('http://upload.snakesandlattes.com/rules/r/ResistanceAvalon.pdf')

    async def av_ping(self, message):
        # av ping: Ping the Avalon bot
        await message.channel.send('pong')

    async def av_coin(self, message):
        # av coin: Simulate a random coin flip
        await message.channel.send(random.choice(['heads', 'tails']))



    async def av_stats(self, message):
        # av stats: Print out the player stats
        with open('avalon_stats', 'rb') as o:
            stats = pickle.load(o)
        if not stats:
            await message.channel.send('No statistical data is currently stored')
        # Figure out which format of data we want
        role = 0
        if message.mentions:
            stats = stats.get(message.mentions[0].id)
            if not stats:
                await message.channel.send('No statistical data exists for this player')
                return
        else:
            content = message.content.split(None, 2)
            if len(content) == 3:
                role_cmd = content[2].lower()
                if role_cmd not in ROLE_COMMANDS[1:]:
                    await message.channel.send('Invalid role "%s": should be one of %s' % (role_cmd, ', '.join(ROLE_COMMANDS[1:])))
                    return
                role = ROLE_COMMANDS.index(role_cmd)
                stats = dict([[id, stats[id][role]] for id in stats if role in stats[id]])
                if not stats:
                    await message.channel.send('No statistical data exists for this role')
                    return
            else:
                stats = dict([(id, [sum([i[0] for i in stats[id].values()]),
                                    sum([i[1] for i in stats[id].values()])]) \
                              for id in stats])
        # Create the rows of data
        rows = []
        for id, (win, loss) in stats.items():
            if message.mentions:
                # id is a role number then
                name = ROLE_NAMES[id]
            else:
                # id is a user id
                p = discord.utils.get(self.get_all_members(), id=id)
                if p is None:
                    continue
                name = p.name
            rows.append([name, win, loss, win+loss, float(win * 100) / (win + loss)])
        # Sort and format the rows
        rows.sort(key = lambda x: x[-1], reverse=True)
        for row in rows:
            row[-1] = ('%.4g%%' % row[-1])
        rows = [list(map(str, row)) for row in rows]
        # Add the header
        rows.insert(0, ['Role' if message.mentions else 'Player', 'Wins', 'Losses', 'Total', 'Win Ratio'])
        lengths = [max([len(row[i]) for row in rows]) for i in range(5)]
        # Add the footer if necessary
        if message.mentions:
            win  = sum([int(i[1]) for i in rows[1:]])
            loss = sum([int(i[2]) for i in rows[1:]])
            rows.append(['Total', str(win), str(loss), str(win+loss), '%.4g%%' % (float(win * 100) / (win + loss))])
        # Print out the descriptive message at the top
        if message.mentions:
            await message.channel.send('**Avalon player stats for %s:**' % message.mentions[0].mention)
        elif role:
            await message.channel.send('**Avalon player stats for %s:**' % ROLE_NAMES[role])
        else:
            await message.channel.send('**Avalon player stats:**')
        # Align the rows
        divider = '+%s+\n' % '+'.join(['-'*l for l in lengths])
        rows = ['|%s|\n' % '|'.join([entry.rjust(l) for entry, l in zip(row, lengths)]) for row in rows]
        table = divider + divider.join(rows) + divider
        # Print out the whole table
        await message.channel.send('```\n%s```' % table)
        
                


    async def av_help(self, message):
        # av help: DMs list of commands
        await message.author.send('''**Avalon bot commands:**

av approve: Vote yes to a proposed team
av assassinate: Try to kill Merlin (if you are the Assassin and it is the end of the game)
av cancel: Cancel a game you created
av coin: Simulate a random coin flip
av create: Create a new game
av disable: Disable a feature of the game
av enable: Enable a feature of the game
av fail: Cause a quest to fail
av help: I'm guessing you've figured out by now what this one does
av info: Print out the current game info
av join: Join a game that has not yet started
av lady: Investigate the alignment of another player using Lady of the Lake
av leave: Leave a game before it begins
av merge: Merge two special roles
av pick: Pick someone as a member of your team (note there is no way to "un-pick" them later!)
av pickme: Shortcut to pick yourself for your own team
av pickrandom: Pick a random person to join your team
av ping: Ping the Avalon bot
av poke: Pokes people who need to make a decision
av reject: Vote no to a proposed team
av roles: Print out info about the gameplay roles
av rules: Gives link to the game rulebook
av start: Start the game that was previously created
av stats: Print out the player stats
av success: Signal that a quest should succeed
av unmerge: Unmerge all previously merged special roles''')






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
        random.shuffle(roles)
        for player, (role, side) in zip(self.players, roles):
            player.role = (role if isinstance(role, tuple) else (role,))
            player.side = side
            names = [ROLE_NAMES[role.value] for role in player.role]
            names = [name for name in names if name not in ('Palm', 'Norebo')] # Palm and Norebo don't know their own identities.
            name = '/'.join(names) or ROLE_NAMES[SERVANT] # `names` should only be empty if it's a good guy whose special role is Palm or Norebo
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
            voting_msg.delete(delay=10) # Delete after 10 seconds
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
        with open('avalon_stats', 'rb') as o:
            stats = pickle.load(o)
        for p in self.players:
            info += '%s: %s\n' % (p.user.mention, '/'.join([ROLE_NAMES[role.value] for role in p.role]))
            pdata = stats.setdefault(p.user.id, {})
            for role in p.role:
                rdata = pdata.setdefault(role.value, [0, 0])
                if p.side == winner:
                    rdata[0] += 1
                else:
                    rdata[1] += 1
        await self.main_channel.send(info)
        with open('avalon_stats', 'wb') as o:
            pickle.dump(stats, o)
        
            
        
        





if __name__ == '__main__':
    client = Avalon()
    client.run(client.TOKEN)
